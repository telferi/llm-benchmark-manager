from pathlib import Path
import pytest
from llmbench.benchmark.aiperf import AIPerfRunner, AIPerfUnavailable, parse_aiperf_report
from llmbench.benchmark.profiles import BASELINE_V1

def test_baseline_profile_is_stable():
    assert (BASELINE_V1.name,BASELINE_V1.isl,BASELINE_V1.osl,BASELINE_V1.requests,BASELINE_V1.concurrency)==("baseline-v1",128,128,10,1)

def test_parser_normalizes_success_and_partial_reports():
    root=Path(__file__).parent/'fixtures'
    ok=parse_aiperf_report(root/'aiperf_success.json')
    assert (ok.success_count,ok.error_count,ok.metrics['ttft_p50'],ok.metrics['e2e_tokens_per_second'])==(10,0,446.8,52.3)
    partial=parse_aiperf_report(root/'aiperf_partial.json')
    assert (partial.success_count,partial.error_count)==(8,2)
    assert partial.errors[0]['http_status']==503 and partial.errors[0]['count']==2

def test_command_never_contains_secret(tmp_path):
    runner=AIPerfRunner(executable='/usr/bin/aiperf')
    cfg=runner.write_config(tmp_path/'cfg.yaml','https://example.test',BASELINE_V1)
    cmd=runner.build_command('model-a',cfg,tmp_path/'artifacts')
    assert 'super-secret' not in ' '.join(cmd)
    assert '${LLMBENCH_PROVIDER_API_KEY}' in Path(cfg).read_text()

def test_run_passes_secret_only_in_environment(tmp_path):
    fake=tmp_path/'aiperf'
    fake.write_text("""#!/usr/bin/env python3
import json,os,sys,pathlib
assert os.environ['LLMBENCH_PROVIDER_API_KEY']=='super-secret'
assert 'super-secret' not in ' '.join(sys.argv)
a=pathlib.Path(sys.argv[sys.argv.index('--artifact-dir')+1]); a.mkdir(parents=True,exist_ok=True)
(a/'profile_export_aiperf.json').write_text(json.dumps({'aiperf_version':'0.test','request_count':{'avg':1},'error_request_count':{'avg':0},'completed_request_count':{'avg':1},'error_summary':[]}))
""")
    fake.chmod(0o755)
    runner=AIPerfRunner(executable=str(fake))
    out=runner.run(model_id='m',base_url='https://example.test',api_key='super-secret',profile=BASELINE_V1,artifact_dir=tmp_path/'out')
    assert out.success_count==1 and out.error_count==0
    assert 'super-secret' not in out.process_output

def test_missing_executable_is_explicit(tmp_path):
    with pytest.raises(AIPerfUnavailable):
        AIPerfRunner(executable=str(tmp_path/'missing')).run(model_id='m',base_url='https://x',api_key='s',profile=BASELINE_V1,artifact_dir=tmp_path/'o')
