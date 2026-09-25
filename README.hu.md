# LLM Benchmark Manager

[English](README.md) | [Magyar](README.hu.md)

Az LLM Benchmark Manager egy önálló, nyílt forráskódú eszköz LLM-szolgáltatók modelljeinek felderítésére, tényleges elérhetőségük ellenőrzésére, képesség- és állapotbesorolására, a kompatibilis szöveges modellek NVIDIA AIPerf mérésére, valamint a történeti eredmények SQLite adatbázisban történő megőrzésére.

Szándékosan független bármely agent-rendszertől, operációs rendszerbeli felhasználónévtől, gépnévtől, könyvtárstruktúrától és routing rendszertől. Használható interaktív CLI-ből, automatizálható REST API-val, illetve AI/agent rendszerből MCP-n keresztül.

## Mit csinál?

Egy teljes futás alapértelmezett folyamata:

1. lekéri a provider modellkatalógusát;
2. minden kiválasztott modellhez tartós progress sort hoz létre;
3. meghatározza vagy óvatosan becsüli a modell képességtípusát;
4. képességhez illő smoke probe-ot futtat;
5. rövid stabilitási ellenőrzést és korlátozott retry-t végez a tranziensekre;
6. csak kompatibilis profil esetén futtat AIPerf benchmarkot;
7. besorolja a modellt (`ACTIVE`, `UNSTABLE`, `NOT_AVAILABLE` stb.);
8. eltárolja a metrikákat, normalizált hibákat, progress állapotot és státusztörténetet SQLite-ban.

Egy későbbi újrateszt nem írja át egy korábbi futás történeti végállapotát.

## Kiadási állapot

Aktuális kiadás: **0.3.1**.

A forráskód nyilvánosan elérhető GitHubon. A kiadási csomagok a GitHub `v*.*.*` release-tag workflow-jából kerülnek PyPI-ra PyPI Trusted Publishing használatával, ezért nincs szükség hosszú élettartamú PyPI API token tárolására a repositoryban.

## Követelmények

- Python 3.11+
- hálózati elérés a tesztelt providerhez
- provider credential, ahol hitelesítés szükséges

**Az NVIDIA AIPerf 0.12.0 kötelező csomagfüggőség.** Az LLM Benchmark Manager telepítése automatikusan telepíti az AIPerfet is; külön AIPerf telepítés nem szükséges.

A beépített AIPerf profil jelenleg a `CHAT_TEXT` modelleket méri. A discovery, capability detection és a nem szöveges probe-ok ugyanebben a telepített alkalmazásban működnek akkor is, ha egy adott modellhez nincs alkalmazható AIPerf profil.

## Telepítés

### Forráskódból

A jelenlegi kiadáshoz ez az ajánlott:

```bash
pipx install .
llmbench --help
```

Fejlesztéshez:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

### Elkészített wheelből

```bash
pipx install dist/llm_benchmark_manager-0.3.1-py3-none-any.whl
llmbench --help
```

### PyPI-ról

```bash
pipx install llm-benchmark-manager
```

### A CLI indítása

Ha a `llmbench` már szerepel a `PATH`-ban, az interaktív felület így indítható:

```bash
llmbench
```

Ha a csomagot `python3 -m pip install --user ...` paranccsal telepítetted, és a shell azt jelzi, hogy a `~/.local/bin` nincs benne a `PATH`-ban, közvetlenül így indíthatod:

```bash
"$HOME/.local/bin/llmbench"
```

Ha azt szeretnéd, hogy a későbbi Bash munkamenetekben elég legyen a `llmbench` parancs, egyszer add hozzá a felhasználói bináris könyvtárat a `PATH`-hoz:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Ezután egyszerűen így indítható:

```bash
llmbench
```

### Docker

```bash
docker build -t llm-benchmark-manager:0.3.1 .
```

REST API példa:

```bash
docker run --rm \
  --env-file providers.env \
  -p 8765:8765 \
  -v llmbench-data:/data \
  llm-benchmark-manager:0.3.1 serve --host 0.0.0.0 --port 8765
```

A konténer az alkalmazás adatait `/data` alatt tárolja. Az AIPerf automatikusan bekerül a képbe, mert normál projektfüggőség.

## Gyors kezdés

Interaktív indítás:

```bash
llmbench
```

Új providernél csak az endpoint URL-t és az API kulcsot kell megadni:

```text
New provider
Endpoint URL: https://provider.example.com
API key: ***************
```

A provider azonosítója az endpoint hostnevéből készül. Ha ugyanaz a normalizált endpoint már létezik, a program a meglévő provider rekordot használja, nem hoz létre duplikátumot.

Meglévő providernél az interaktív menü tud:

- teljes újratesztet;
- csak `ACTIVE` modellek újratesztjét;
- `UNSTABLE`/`FAILED` újratesztet;
- modellkatalógus-frissítést és csak `NEW` modellek tesztjét;
- egyetlen modell célzott tesztjét;
- ismert modellek és állapotuk listázását.

## Automatizálható CLI

```bash
llmbench provider list
llmbench provider discover PROVIDER

llmbench run PROVIDER --mode full
llmbench run PROVIDER --mode new
llmbench run PROVIDER --mode active
llmbench run PROVIDER --mode unstable_failed
llmbench run --all --mode full

llmbench model test PROVIDER MODEL_ID
llmbench results RUN_ID
llmbench history PROVIDER MODEL_ID
llmbench export RUN_ID --format json --output run.json
llmbench export RUN_ID --format csv --output run.csv
```

A `PROVIDER` a szolgáltatás által elfogadott konfigurált provider ID/slug.

## Provider kompatibilitás

A beépített általános adapter OpenAI-kompatibilis API-kat céloz, tipikusan:

- `/v1/models`
- `/v1/chat/completions`
- `/v1/embeddings`

A provider-specifikus eltérések kezelése szándékosan konzervatív. Például ha egy asymmetric embedding modell kifejezetten jelzi, hogy kötelező az `input_type`, a program újrapróbálja `input_type="query"` értékkel. Más HTTP 400 hibákra nem erőltet rá vakon provider-specifikus paramétert.

Egy provider katalógusa tartalmazhat olyan modellt is, amely az aktuális fiókkal vagy endpointtal nem hívható. Ezt a program külön kezeli a valóban hibás modelltől.

## Modellállapotok

- `NEW` — felderített, de még nem értékelt modell.
- `ACTIVE` — átment a támogatott probe-on és, ha alkalmazható, a kompatibilis benchmark profilon.
- `UNSTABLE` — használható, de tranzienst vagy részleges benchmark hibát láttunk.
- `NOT_AVAILABLE` — felderíthető, de az aktuális provider/fiók/endpoint kombinációval nem hívható. A híváskori HTTP 404 tipikusan ide kerül.
- `INCOMPATIBLE` — az általános request forma nem illik a modell képességéhez.
- `UNSUPPORTED` — a capability ismert, de ehhez a kiadáshoz nincs biztonságos általános probe/benchmark út.
- `FAILED` — a helyes, támogatott request útvonalon determinisztikus, nem tranzienseként értelmezhető hiba történt.
- `DISABLED` — kézzel kizárt modell.
- `MISSING` — korábban ismert modell, amelyet a discovery már nem ad vissza.

Egy későbbi retest nem módosítja visszamenőleg egy régi run státusz-összesítését.

## Capability-k

A capability külön adat a modell egészségi állapotától:

- `CHAT_TEXT`
- `EMBEDDING`
- `VISION`
- `MULTIMODAL`
- `PARSER`
- `TRANSLATION`
- `SAFETY`
- `RERANK`
- `SPECIAL`
- `UNKNOWN`

A felismerés sorrendje konzervatív: provider metadata, modell-ID heurisztika, probe-visszajelzés vagy kézi forrás. Pusztán egy capability-becslés nem jelöl modellt hibásnak.

## Retry és hibabesorolás

Az alapértelmezett szabályok különválasztják a provider/fiók elérhetőségét a modell minőségétől:

- `401` / `403` → authentication/provider run probléma, nem modellhiba;
- `404` → `NOT_AVAILABLE`, azonos kérésre nincs retry;
- `429` → rate limit, korlátozott 1/2/5/10 másodperces retry vagy provider `Retry-After`;
- `503` → túlterhelés, korlátozott 1/2/5/10 másodperces retry;
- `500` / `502` / `504` → tranzienseként kezelt provider hiba, 1/3 másodperces retry;
- timeout/network hiba → tranzienseként kezelt, 1/3 másodperces retry;
- capability mismatchot jelentő `400` → `INCOMPATIBLE`;
- helyes request formán jelentkező determinisztikus payload hiba → `FAILED`.

Ha a modell csak retry után működik, `UNSTABLE` állapotot kap.

## AIPerf benchmark profil

A beépített `baseline-v1` kompatibilis `CHAT_TEXT` modellekhez:

- input sequence length: 128 token;
- output sequence length: 128 token;
- 10 kérés;
- concurrency: 1;
- streaming: bekapcsolva;
- determinisztikus synthetic seed: 42.

A provider API kulcs környezeti változóként kerül az AIPerf child processhez, soha nem parancssori argumentumként. Az ideiglenes AIPerf konfigurációs fájl a futás végén törlődik.

`EMBEDDING` és más speciális capability-k nem futnak át erőltetetten a text-generation AIPerf profilon. Ezért egy sikeres nem szöveges modell végeredménye lehet `ACTIVE`, miközben a benchmark outcome `SKIPPED_UNSUPPORTED_PROFILE`.

## Progress és történet

Minden kiválasztott modell már a futás elején kap `run_model_progress` sort. Ezért a progress akkor is pontos, ha sok felderített modell el sem jut az AIPerfig.

Példa:

```text
[37/82] 45.1%  provider/model-id
Capability: CHAT_TEXT
Smoke: PASS
Stability: PASS
AIPerf: RUNNING
```

Progress állapotok:

- `PENDING`
- `CAPABILITY`
- `SMOKE`
- `STABILITY`
- `BENCHMARK`
- `DONE`

A futás akkor teljes, amikor minden kiválasztott sor `DONE`.

## Credential és secret kezelés

Interaktív API kulcs soha nem kerül SQLite adatbázisba.

Tárolási sorrend:

1. operációs rendszer keyringje, ha használható backend elérhető;
2. titkosított helyi credential vault, ha nincs használható keyring;
3. környezeti változó hivatkozás automatizáláshoz, konténerhez vagy service futtatáshoz.

A titkosított fallback Fernet alapú lokális master keyt és vaultot használ az alkalmazás adatkönyvtárában. A fájlok korlátozott jogosultságot kapnak, ahol ezt az operációs rendszer támogatja. A helyi OS user továbbra is a trust boundary része; ez nem hardware-backed secret store.

ENV automatizálási példa:

```bash
export PROVIDER_API_KEY='...'

llmbench provider add \
  --slug example \
  --name 'Example Provider' \
  --url 'https://provider.example.com' \
  --credential-env PROVIDER_API_KEY
```

Csak a környezeti változó neve kerül eltárolásra.

A provider hibaüzenetek tárolás előtt tisztítva vannak: aktív secretek, bearer tokenek, UUID-szerű request azonosítók és account-szerű azonosítók maszkolódnak vagy normalizálódnak, a hibaüzenetek pedig hosszkorlátosak.

## Adatkönyvtár

Az alapértelmezett adatkönyvtárat a `platformdirs` választja ki, tehát nincs beégetett felhasználónév vagy home útvonal.

Tipikus helyek:

- Linux: `~/.local/share/llmbench/`
- macOS: `~/Library/Application Support/llmbench/`
- Windows: az aktuális felhasználó helyi application-data könyvtárának `llmbench` alkönyvtára

Bármikor felülírható:

```bash
export LLMBENCH_DATA_DIR=/path/to/llmbench-data
```

Tartalma:

```text
llmbench.db
artifacts/
credentials/     # csak encrypted-file fallback használatakor
```

A program nem feltételez konkrét felhasználónevet, szervernevet vagy telepítési könyvtárat.

## AIPerf executable feloldása

Az AIPerf kötelező dependency. A program ebben a sorrendben keresi a futtatható állományt:

1. `LLMBENCH_AIPERF` explicit felülírás;
2. a `llmbench`-et futtató Python interpreter mellé telepített `aiperf` — ez különösen fontos `pipx` környezetben;
3. `PATH` alatt található `aiperf`.

Felülírás példa:

```bash
export LLMBENCH_AIPERF=/custom/venv/bin/aiperf
```

## REST API

Helyi indítás:

```bash
llmbench serve --host 127.0.0.1 --port 8765
```

Fő erőforrások:

```text
GET  /api/v1/providers
POST /api/v1/providers
GET  /api/v1/providers/{provider_id}
POST /api/v1/providers/{provider_id}/discover
GET  /api/v1/providers/{provider_id}/models

POST /api/v1/runs
GET  /api/v1/runs/{run_id}
GET  /api/v1/runs/{run_id}/progress
POST /api/v1/runs/{run_id}/cancel
GET  /api/v1/runs/{run_id}/results

GET  /api/v1/models/{model_db_id}
GET  /api/v1/models/{model_db_id}/history
```

A 0.3.1 REST API-nak nincs beépített multi-user authentication rétege. Az alapértelmezett bind loopback. Megbízhatatlan hálózatra csak külön authentication/network-control réteg mögött szabad kitenni.

## MCP szerver

Indítás:

```bash
llmbench mcp
```

MCP toolok:

```text
benchmark_provider_list
benchmark_provider_get
benchmark_provider_discover
benchmark_model_list
benchmark_model_get
benchmark_model_history
benchmark_run_start
benchmark_run_status
benchmark_run_progress
benchmark_run_cancel
benchmark_run_results
benchmark_retest_unstable
benchmark_test_new_models
```

Szándékosan nincs olyan MCP tool, amely nyers provider credentialt ad vissza.

Így egy külső agent — például Model Designer — discoveryt és benchmarkot kérhet anélkül, hogy hozzáférést kapna az API kulcsokhoz.

## Export

```bash
llmbench export RUN_ID --format json --output run.json
llmbench export RUN_ID --format csv --output run.csv
```

A helyi SQLite adatbázis marad az elsődleges történeti forrás.

## Biztonsági megjegyzések

- Provider credential nem kerül normál adatbázis rekordba vagy API/MCP válaszba.
- Az AIPerf a credentialt környezeti változóban kapja, nem argv-ban.
- A tárolt provider hibaüzenetek tisztítva vannak.
- Interaktív secret bevitel rejtett terminál-inputtal történik.
- Provider URL nem tartalmazhat beágyazott user/password credentialt.
- A REST szolgáltatást külső auth nélkül privát hálózaton kell tartani.
- Aki ugyanazon OS userként olvasni tudja az encrypted fallback master keyt és vaultot, az a credentialt is vissza tudja fejteni; erősebb izolációhoz OS keyring vagy külső secret manager javasolt.

Részletesen: [SECURITY.md](SECURITY.md).

## Architektúra

```text
CLI / REST / MCP
      |
BenchmarkService
      |
+-----+------------------+
|                        |
Provider adapter       SQLite
|                        |
Discovery/probes      history/progress
|
AIPerfRunner (CHAT_TEXT baseline)
```

Az LLM Benchmark Manager nem routing rendszer, és nem módosít production routing konfigurációt. Külső rendszerek a CLI/REST/MCP/export eredményeit használják fel.

Részletesen: [docs/ARCHITECTURE.hu.md](docs/ARCHITECTURE.hu.md).

## Fejlesztés és ellenőrzés

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest -q
python -m build
python -m pip check
```

Kiadás előtt külön tiszta környezetben is telepíteni kell a wheelt, és ellenőrizni kell a `llmbench --help` és `aiperf --version` parancsot.

## Közreműködés

Közreműködés szívesen fogadott; lásd [CONTRIBUTING.md](CONTRIBUTING.md). Valós API kulcsot, provider account azonosítót, helyi adatbázist vagy privát benchmark artifactot ne tegyél issue-ba vagy commitba.

## Licenc

MIT. Lásd [LICENSE](LICENSE).
