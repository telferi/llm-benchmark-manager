from dataclasses import dataclass

@dataclass(frozen=True)
class BenchmarkProfile:
    name:str
    isl:int=128
    osl:int=128
    requests:int=10
    concurrency:int=1
    streaming:bool=True
    tokenizer:str='builtin'
    timeout_seconds:int=300

BASELINE_V1=BenchmarkProfile('baseline-v1')
STABILITY_V1=BenchmarkProfile('stability-v1',isl=64,osl=32,requests=3,concurrency=1)
THROUGHPUT_V1=BenchmarkProfile('throughput-v1',isl=128,osl=128,requests=30,concurrency=4)
