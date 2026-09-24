from __future__ import annotations
import argparse, json, re, getpass
from dataclasses import asdict
from .runtime import build_runtime
from .export import export_run

def build_parser():
    p=argparse.ArgumentParser(prog='llmbench',description='Provider-agnostic LLM benchmark manager')
    sub=p.add_subparsers(dest='command')
    provider=sub.add_parser('provider'); ps=provider.add_subparsers(dest='provider_command')
    a=ps.add_parser('add'); a.add_argument('--slug',required=True); a.add_argument('--name',required=True); a.add_argument('--url',required=True); a.add_argument('--type',default='openai-compatible'); a.add_argument('--credential-env',required=True)
    ps.add_parser('list'); d=ps.add_parser('discover'); d.add_argument('provider')
    run=sub.add_parser('run'); run.add_argument('provider',nargs='?'); run.add_argument('--all',action='store_true'); run.add_argument('--mode',choices=['full','new','active','unstable','unstable_failed','failed'],default='full')
    results=sub.add_parser('results'); results.add_argument('run_id')
    history=sub.add_parser('history'); history.add_argument('provider'); history.add_argument('model_id')
    model=sub.add_parser('model'); ms=model.add_subparsers(dest='model_command'); mt=ms.add_parser('test'); mt.add_argument('provider'); mt.add_argument('model_id')
    ex=sub.add_parser('export'); ex.add_argument('run_id'); ex.add_argument('--format',choices=['json','csv'],required=True); ex.add_argument('--output',required=True)
    serve=sub.add_parser('serve'); serve.add_argument('--host',default='127.0.0.1'); serve.add_argument('--port',type=int,default=8765)
    mcp=sub.add_parser('mcp'); mcp.add_argument('--transport',default='stdio')
    return p



_STATUS_ORDER=("ACTIVE","UNSTABLE","NOT_AVAILABLE","INCOMPATIBLE","UNSUPPORTED","FAILED")

def _render_progress(snapshot: dict) -> None:
    event=snapshot.get("event") or {}
    current=snapshot.get("current") or {}
    model_id=event.get("model_id") or current.get("model_id")
    if not model_id:
        return
    total=int(snapshot.get("total",0) or 0)
    processed=int(snapshot.get("processed",0) or 0)
    percent=float(snapshot.get("percent",0.0) or 0.0)
    stage=event.get("stage") or current.get("stage") or "PENDING"
    capability=event.get("capability") or current.get("capability") or "UNKNOWN"
    outcome=event.get("outcome")
    print(f"[{processed}/{total}] {percent:.1f}%  {model_id}")
    print(f"Capability: {capability}")
    label={"SMOKE":"Smoke","STABILITY":"Stability","BENCHMARK":"AIPerf","CAPABILITY":"Capability stage","DONE":"Done"}.get(stage,stage.title())
    if stage != "CAPABILITY":
        print(f"{label}: {outcome or 'RUNNING'}")

def _render_run_summary(snapshot: dict) -> None:
    counts=snapshot.get("by_status") or {}
    print("Run summary:")
    for status in _STATUS_ORDER:
        print(f"{status}: {int(counts.get(status,0) or 0)}")
    print(f"Total processed: {int(snapshot.get('processed',0) or 0)}")

def _execute_with_progress(service, run):
    done=service.execute_run(run.id,progress_callback=_render_progress)
    _render_run_summary(service.run_progress(run.id))
    return done

def _normalize_env_name(value: str) -> str | None:
    raw=value.strip()
    if raw.startswith('${') and raw.endswith('}'):
        raw=raw[2:-1].strip()
    elif raw.startswith('$'):
        raw=raw[1:].strip()
    return raw if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',raw or '') else None

def _prompt_env_name() -> str:
    while True:
        raw=input('API credential ENV variable (e.g. NVIDIA_API_KEY): ').strip()
        env=_normalize_env_name(raw)
        if env:
            return env
        print('Invalid ENV variable name. Enter only the variable name, for example NVIDIA_API_KEY (a leading $ is also accepted).')

def _provider_lines(service):
    lines=[]
    for x in service.list_providers():
        available=service.credentials.availability(x.credential_ref,x.credential_source)
        lines.append(f'{x.id}. {x.slug} — {x.name} [{x.credential_ref}: {"FOUND" if available else "MISSING"}]')
    return lines

def _interactive(service,jobs):
    while True:
        print('\nLLM Benchmark Manager\n')
        print('1. New provider')
        print('2. Existing provider')
        print('3. Retest all providers')
        print('4. View previous results')
        print('5. Settings')
        print('6. Exit')
        choice=input('Choice: ').strip()
        if choice=='6': return 0
        if choice=='1':
            url=input('Endpoint URL: ').strip(); api_key=getpass.getpass('API key: ')
            try:
                pr=service.add_provider_with_secret(url,api_key)
            except Exception as e:
                print(f'Provider could not be added: {e}'); continue
            available=service.credentials.availability(pr.credential_ref,pr.credential_source)
            print(f'Added {pr.slug}. Credential: {"STORED" if available else "MISSING"} ({pr.credential_source})')
            if available:
                try:
                    found=service.discover(pr.id); run=service.create_run(pr.id,'full'); done=_execute_with_progress(service,run)
                    print(f'Discovered {len(found.seen)} models. Benchmark {run.id}: {done.status.value}')
                except Exception as e:
                    print(f'Automatic onboarding failed: {e}')
        elif choice=='2':
            providers=service.list_providers()
            if not providers: print('No providers configured.'); continue
            for line in _provider_lines(service): print(line)
            raw=input('Provider id: ').strip()
            try: pr=service.resolve_provider(raw)
            except Exception as e: print(f'Error: {e}'); continue
            print('1. Full retest\n2. ACTIVE only\n3. UNSTABLE/FAILED only\n4. Refresh models + test NEW\n5. Test one model\n6. Show models\n7. Back')
            action=input('Choice: ').strip()
            if action=='7': continue
            if action=='4': service.discover(pr.id); mode='new'
            elif action=='1': mode='full'
            elif action=='2': mode='active'
            elif action=='3': mode='unstable_failed'
            elif action=='5':
                model_id=input('Model id: ').strip(); run=service.create_run(pr.id,'full',model_id=model_id); done=_execute_with_progress(service,run); print(f'{run.id}: {done.status.value}'); continue
            elif action=='6':
                for m in service.db.list_models(pr.id): print(f'{m.model_id}\t{m.status.value}')
                continue
            else: continue
            run=service.create_run(pr.id,mode); done=_execute_with_progress(service,run); print(f'{run.id}: {done.status.value}')
        elif choice=='3':
            for pr in service.list_providers():
                run=service.create_run(pr.id,'full'); done=_execute_with_progress(service,run); print(f'{pr.slug}: {done.status.value}')
        elif choice=='4':
            rid=input('Run id: ').strip(); print(json.dumps(service.results(rid),indent=2,default=str))
        elif choice=='5': print('Interactive provider keys use the OS keyring when available, with encrypted local fallback. ENV credentials remain supported for automation.')

def main(argv=None,service=None,jobs=None):
    parser=build_parser(); args=parser.parse_args(argv)
    if service is None or jobs is None:
        default_service,default_jobs=build_runtime(); service=service or default_service; jobs=jobs or default_jobs
    if args.command is None: return _interactive(service,jobs)
    if args.command=='provider':
        if args.provider_command=='add':
            x=service.add_provider(args.slug,args.name,args.type,args.url,args.credential_env); print(f'{x.id}\t{x.slug}\t{x.credential_ref}'); return 0
        if args.provider_command=='list':
            for line in _provider_lines(service): print(line)
            return 0
        if args.provider_command=='discover':
            r=service.discover(args.provider); print(f'new={len(r.new)} seen={len(r.seen)} missing={len(r.missing)}'); return 0
        parser.error('provider subcommand required')
    if args.command=='run':
        targets=service.list_providers() if args.all else [service.resolve_provider(args.provider)]
        for pr in targets:
            run=service.create_run(pr.id,args.mode); done=_execute_with_progress(service,run); print(f'{run.id}\t{pr.slug}\t{done.status.value}')
        return 0
    if args.command=='model' and args.model_command=='test':
        run=service.create_run(args.provider,'full',model_id=args.model_id); done=_execute_with_progress(service,run); print(f'{run.id}\t{done.status.value}'); return 0
    if args.command=='results': print(json.dumps(service.results(args.run_id),indent=2,default=str)); return 0
    if args.command=='history': print(json.dumps(service.model_history(args.provider,args.model_id),indent=2,default=str)); return 0
    if args.command=='export': print(export_run(service.db,args.run_id,args.format,args.output)); return 0
    if args.command=='serve':
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(service,jobs),host=args.host,port=args.port); return 0
    if args.command=='mcp':
        from .mcp_server import build_mcp_server
        build_mcp_server(service,jobs).run(transport=args.transport); return 0
    parser.error('unknown command')

if __name__=='__main__': raise SystemExit(main())
