# Architektúra

## Tervezési cél

Az LLM Benchmark Manager bizonyítékot előállító szolgáltatás. Modelleket derít fel és tesztel, eltárolja a történteket, majd az eredményt elérhetővé teszi. Szándékosan **nem** hoz production routing döntést, és nem függ semmilyen konkrét agent keretrendszertől vagy routing platformtól.

## Fő komponensek

### Felületek

- **CLI** — interaktív használat és shell automatizálás.
- **REST API** — helyi vagy kontrollált hálózati automatizálás.
- **MCP szerver** — agent/tool integráció credential átadás nélkül.

Mindegyik ugyanazt a `BenchmarkService` magot használja.

### BenchmarkService

Összefogja a provider discoveryt, modellkiválasztást, capability detektálást, smoke/stability probe-okat, retry szabályokat, AIPerf jogosultságot, végső besorolást és persistence réteget.

### Provider adapter

Az alap adapter OpenAI-kompatibilis model listing, chat és embedding végpontokat kezel. Provider-specifikus workaround csak egyértelmű válaszjelzés alapján aktiválódhat, lehetőleg nem pusztán providernév alapján.

### Capability réteg

A capability külön tárolódik a health státusztól. A felismerés metadata, konzervatív modellnév-heurisztika és probe evidence alapján történhet. Ismeretlen vagy speciális modelleket a rendszer megőriz; nem kényszeríti őket hibás request formába.

### AIPerf adapter

Az AIPerf 0.12.0 kötelező Python dependency. A jelenlegi `baseline-v1` profil kompatibilis `CHAT_TEXT` modellekre alkalmazható. A credential child-process environmentben kerül átadásra, az ideiglenes config a futás után törlődik.

### SQLite

Tárolt adatok:

- providerek;
- felderített modellek;
- capability metadata;
- benchmark runok;
- modellenkénti progress;
- benchmark metrikák;
- normalizált hibák;
- státusztörténet.

A történeti run bizonyíték: egy későbbi modellállapot-változás nem írja át a korábbi run összesítését.

### Credential manager

A credential csak tényleges provider híváskor oldódik fel. Tárolási lehetőség: OS keyring, titkosított helyi fallback vagy ENV referencia. Az adatbázis raw API kulcs helyett csak forrás- és referenciaadatot tárol.

## Adatfolyam

```text
provider discovery
      |
kiválasztott run modellek
      |
capability detection
      |
capability-aware smoke
      |
stability / bounded retry
      |
profile eligibility
      +---- nincs kompatibilis profil ---> végső besorolás
      |
AIPerf baseline
      |
végső besorolás
      |
SQLite history + progress + metrics/errors
```

## Integrációs határ

Egy külső modellmenedzsment rendszer bizonyítékforrásként használhatja:

```text
Model Designer / automatizálás
          |
       MCP/REST
          |
LLM Benchmark Manager
          |
 evidence/history
```

A külső rendszer eldöntheti, hogyan promotál vagy ütemez modelleket; ez a policy szándékosan nem része ennek a repónak.
