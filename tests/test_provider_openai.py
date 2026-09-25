import httpx
from llmbench.providers.openai_compatible import OpenAICompatibleProvider, normalize_error

def test_discovery_normalizes_v1_and_sets_auth():
    seen=[]
    def handler(req):
        seen.append(req)
        return httpx.Response(200,json={"data":[{"id":"m1"},{"id":"m2"}]})
    client=httpx.Client(transport=httpx.MockTransport(handler))
    p=OpenAICompatibleProvider("https://api.example.test/v1",client=client)
    models=p.discover_models("sekret")
    assert [m.model_id for m in models] == ["m1","m2"]
    assert str(seen[0].url) == "https://api.example.test/v1/models"
    assert seen[0].headers["Authorization"] == "Bearer sekret"

def test_discovery_adds_v1_when_missing():
    seen=[]
    client=httpx.Client(transport=httpx.MockTransport(lambda req:(seen.append(req) or httpx.Response(200,json={"data":[]}))))
    OpenAICompatibleProvider("https://api.example.test",client=client).discover_models("k")
    assert str(seen[0].url) == "https://api.example.test/v1/models"

def test_smoke_classifies_overload_and_empty_content():
    client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(503,json={"error":{"message":"Service temporarily overloaded"}})))
    p=OpenAICompatibleProvider("https://api.example.test",client=client)
    r=p.smoke_test("m","k")
    assert (r.ok,r.error_type,r.retryable) == (False,"OVERLOADED",True)
    client2=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={"choices":[{"message":{"content":""}}]})))
    r2=OpenAICompatibleProvider("https://api.example.test",client=client2).smoke_test("m","k")
    assert r2.error_type == "EMPTY_RESPONSE"

def test_error_normalization():
    assert normalize_error(401,"x")[0] == "AUTH_ERROR"
    assert normalize_error(429,"x") == ("RATE_LIMITED",True)
    assert normalize_error(503,"x") == ("OVERLOADED",True)
    assert normalize_error(400,"x")[0] == "PAYLOAD_ERROR"

def test_network_error_is_retryable():
    def handler(req): raise httpx.ConnectError('connection reset',request=req)
    client=httpx.Client(transport=httpx.MockTransport(handler))
    r=OpenAICompatibleProvider('https://api.example.test',client=client).smoke_test('m','k')
    assert r.ok is False and r.error_type=='NETWORK_ERROR' and r.retryable is True


def test_probe_chat_accepts_alternate_reasoning_output():
    from llmbench.domain import ModelCapability
    client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={"choices":[{"message":{"content":None,"reasoning_content":"hello"}}]})))
    r=OpenAICompatibleProvider("https://api.example.test",client=client).probe("m","k",ModelCapability.CHAT_TEXT)
    assert r.ok is True
    assert r.content == "hello"


def test_probe_embedding_uses_embeddings_endpoint_and_validates_vector():
    import json
    from llmbench.domain import ModelCapability
    seen=[]
    def handler(req):
        seen.append((str(req.url), json.loads(req.content.decode())))
        return httpx.Response(200,json={"data":[{"embedding":[0.1,0.2,0.3]}]})
    client=httpx.Client(transport=httpx.MockTransport(handler))
    r=OpenAICompatibleProvider("https://api.example.test",client=client).probe("embed-model","k",ModelCapability.EMBEDDING)
    assert r.ok is True
    assert len(seen) == 1
    assert seen[0][0] == "https://api.example.test/v1/embeddings"
    assert seen[0][1]["model"] == "embed-model"
    assert isinstance(seen[0][1]["input"], str) and seen[0][1]["input"]


def test_probe_unsupported_capabilities_perform_no_http():
    from llmbench.domain import ModelCapability
    called=[]
    def handler(req):
        called.append(req)
        raise AssertionError("HTTP must not be called for unsupported generic capability")
    p=OpenAICompatibleProvider("https://api.example.test",client=httpx.Client(transport=httpx.MockTransport(handler)))
    caps=(ModelCapability.PARSER,ModelCapability.TRANSLATION,ModelCapability.SAFETY,ModelCapability.RERANK,ModelCapability.SPECIAL,ModelCapability.VISION,ModelCapability.MULTIMODAL)
    for cap in caps:
        r=p.probe("m","k",cap)
        assert r.ok is False
        assert r.error_type == "UNSUPPORTED"
        assert r.retryable is False
    assert called == []


def test_benchmark_profile_is_only_text_baseline():
    from llmbench.domain import ModelCapability
    p=OpenAICompatibleProvider("https://api.example.test")
    assert p.benchmark_profile_for(ModelCapability.CHAT_TEXT) == "baseline-v1"
    assert p.benchmark_profile_for(ModelCapability.EMBEDDING) is None
    assert p.benchmark_profile_for(ModelCapability.PARSER) is None


def test_rate_limit_probe_captures_numeric_retry_after():
    from llmbench.domain import ModelCapability
    client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(429,headers={'Retry-After':'7'},json={'error':{'message':'rate limited'}})))
    r=OpenAICompatibleProvider('https://api.example.test',client=client).probe('m','k',ModelCapability.CHAT_TEXT)
    assert r.error_type=='RATE_LIMITED'
    assert r.retry_after_seconds==7.0


def test_probe_embedding_retries_asymmetric_model_with_query_input_type():
    import json
    from llmbench.domain import ModelCapability
    seen=[]
    def handler(req):
        payload=json.loads(req.content.decode())
        seen.append(payload)
        if len(seen)==1:
            return httpx.Response(400,json={"error":{"message":"'input_type' parameter is required for asymmetric models"}})
        return httpx.Response(200,json={"data":[{"embedding":[0.4,0.5]}]})
    client=httpx.Client(transport=httpx.MockTransport(handler))
    r=OpenAICompatibleProvider("https://integrate.api.nvidia.com",client=client).probe(
        "nvidia/llama-nemotron-embed-vl-1b-v2","k",ModelCapability.EMBEDDING
    )
    assert r.ok is True
    assert len(seen)==2
    assert "input_type" not in seen[0]
    assert seen[1]["input_type"]=="query"


def test_probe_embedding_does_not_retry_unrelated_payload_error_with_input_type():
    import json
    from llmbench.domain import ModelCapability
    seen=[]
    def handler(req):
        seen.append(json.loads(req.content.decode()))
        return httpx.Response(400,json={"error":{"message":"invalid dimensions"}})
    client=httpx.Client(transport=httpx.MockTransport(handler))
    r=OpenAICompatibleProvider("https://integrate.api.nvidia.com",client=client).probe(
        "embed-model","k",ModelCapability.EMBEDDING
    )
    assert r.ok is False
    assert r.error_type=="PAYLOAD_ERROR"
    assert len(seen)==1
