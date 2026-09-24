from __future__ import annotations
import os
class CredentialUnavailable(RuntimeError): pass
class EnvCredentialResolver:
    def resolve(self,ref:str)->str:
        value=os.environ.get(ref)
        if not value: raise CredentialUnavailable(f'Credential environment variable is unavailable: {ref}')
        return value
    def availability(self,ref:str)->bool: return bool(os.environ.get(ref))
def redact_mapping(value):
    sensitive=('authorization','api_key','apikey','token','secret','password')
    if isinstance(value,dict): return {k:('<redacted>' if any(s in k.lower() for s in sensitive) else redact_mapping(v)) for k,v in value.items()}
    if isinstance(value,list): return [redact_mapping(x) for x in value]
    return value

def redact_text(value, secrets=()):
    text='' if value is None else str(value)
    for secret in secrets:
        if secret: text=text.replace(str(secret),'<redacted>')
    return text
