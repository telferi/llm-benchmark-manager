from __future__ import annotations
import json, os, shutil, subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml
from .profiles import BenchmarkProfile

class AIPerfUnavailable(RuntimeError): pass
class AIPerfError(RuntimeError): pass

@dataclass(frozen=True)
class BenchmarkOutcome:
    success_count:int
    error_count:int
    metrics:dict[str,Any]
    errors:list[dict[str,Any]]
    aiperf_version:str|None=None
    artifact_path:str|None=None
    process_output:str=''


def _metric(data,name,field='avg'):
    value=data.get(name)
    return value.get(field) if isinstance(value,dict) else None

def parse_aiperf_report(path:str|Path)->BenchmarkOutcome:
    p=Path(path); data=json.loads(p.read_text())
    success=int(_metric(data,'request_count') or 0)
    errors=int(_metric(data,'error_request_count') or 0)
    metrics={
        'ttft_avg':_metric(data,'time_to_first_token','avg'),
        'ttft_p50':_metric(data,'time_to_first_token','p50'),
        'ttft_p90':_metric(data,'time_to_first_token','p90'),
        'latency_avg':_metric(data,'request_latency','avg'),
        'latency_p50':_metric(data,'request_latency','p50'),
        'latency_p90':_metric(data,'request_latency','p90'),
        'output_tokens_per_second':_metric(data,'output_token_throughput_per_user','avg'),
        'e2e_tokens_per_second':_metric(data,'e2e_output_token_throughput','avg'),
        'inter_token_latency':_metric(data,'inter_token_latency','avg'),
        'request_throughput':_metric(data,'request_throughput','avg'),
        'benchmark_duration':_metric(data,'benchmark_duration','avg'),
        'request_error_rate':_metric(data,'request_error_rate','avg'),
        'completed_request_count':_metric(data,'completed_request_count','avg'),
    }
    normalized=[]
    for item in data.get('error_summary',[]) or []:
        d=item.get('error_details',{}) or {}
        normalized.append({'http_status':d.get('code'),'error_type':d.get('type') or 'INFERENCE_ERROR','message':d.get('message',''),'count':int(item.get('count',1))})
    return BenchmarkOutcome(success,errors,metrics,normalized,data.get('aiperf_version'),str(p))

class AIPerfRunner:
    def __init__(self,executable:str='aiperf'):
        self.executable=executable
    def _check_executable(self):
        if os.sep in self.executable:
            if not Path(self.executable).is_file(): raise AIPerfUnavailable(f'AIPerf executable not found: {self.executable}')
        elif shutil.which(self.executable) is None:
            raise AIPerfUnavailable(f'AIPerf executable not found on PATH: {self.executable}')
    def write_config(self,path:str|Path,base_url:str,profile:BenchmarkProfile):
        p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
        cfg={'schemaVersion':'2.0','random_seed':42,'benchmark':{'model':'__MODEL__','endpoint':{'url':base_url.rstrip('/'),'type':'chat','streaming':profile.streaming,'api_key':'${LLMBENCH_PROVIDER_API_KEY}'},'dataset':{'type':'synthetic','entries':1,'prompts':{'isl':profile.isl,'osl':profile.osl}},'phases':{'type':'concurrency','concurrency':profile.concurrency,'requests':profile.requests}}}
        p.write_text(yaml.safe_dump(cfg,sort_keys=False)); p.chmod(0o600); return p
    def build_command(self,model_id:str,config_path:str|Path,artifact_dir:str|Path,profile:BenchmarkProfile|None=None):
        tokenizer=(profile.tokenizer if profile else 'builtin')
        return [self.executable,'profile','--config',str(config_path),'--model',model_id,'--tokenizer',tokenizer,'--artifact-dir',str(artifact_dir)]
    def run(self,*,model_id:str,base_url:str,api_key:str,profile:BenchmarkProfile,artifact_dir:str|Path,extra_inputs:dict[str,Any]|None=None):
        self._check_executable(); art=Path(artifact_dir); art.mkdir(parents=True,exist_ok=True); art.chmod(0o700)
        cfg_path=art/'.llmbench-aiperf.yaml'; self.write_config(cfg_path,base_url,profile)
        cmd=self.build_command(model_id,cfg_path,art,profile)
        if extra_inputs:
            cmd += ['--extra-inputs',json.dumps(extra_inputs,separators=(',',':'))]
        env=os.environ.copy(); env['LLMBENCH_PROVIDER_API_KEY']=api_key
        try:
            proc=subprocess.run(cmd,env=env,text=True,capture_output=True,timeout=profile.timeout_seconds,check=False)
        except FileNotFoundError as e:
            raise AIPerfUnavailable(f'AIPerf executable not found: {self.executable}') from e
        except subprocess.TimeoutExpired as e:
            raise AIPerfError(f'AIPerf timed out after {profile.timeout_seconds}s') from e
        finally:
            try: cfg_path.unlink()
            except FileNotFoundError: pass
        output=((proc.stdout or '')+'\n'+(proc.stderr or '')).replace(api_key,'<redacted>')
        reports=sorted(art.glob('profile_export_aiperf*.json'))
        if not reports:
            raise AIPerfError(f'AIPerf failed rc={proc.returncode}: {output[-2000:]}')
        parsed=parse_aiperf_report(reports[-1])
        return BenchmarkOutcome(parsed.success_count,parsed.error_count,parsed.metrics,parsed.errors,parsed.aiperf_version,parsed.artifact_path,output)
