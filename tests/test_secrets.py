"""Only synthetic configuration and isolated local keys; no host project secrets."""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import secret_permissions as perm
import secrets_tools as tools
import secrets_vault as vault


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    root=tmp_path/'project';root.mkdir();home=tmp_path/'home';home.mkdir()
    monkeypatch.setenv('HOME',str(home));monkeypatch.setattr(vault,'ROOT',root)
    values={'.env':b"STRIPE_SECRET_KEY=sk_test_FICTITIOUS_ONLY\r\nPASSWORD='un # $ secret fictif'\r\n",
            '.camera-agent.json':'{"token":"jeton fictif", "camera_index":1, "comment":"caméra"}'.encode(),
            'esp8266-led/include/secrets.h':b'#define WIFI_PASSWORD "fictitious-only"\n\0'}
    for name,data in values.items():
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    return root,home,values


@pytest.fixture
def actual_tools(isolated,monkeypatch):
    # CI fixture location outside the delivered project. Actual official binaries.
    assets=ROOT.parent/'tmp/sops-assets'
    if not (assets/'sops-v3.12.2.linux.amd64').exists():
        pytest.skip('Official test binaries not provisioned; host ansible/Stripe not involved')
    def local_download(url,expected):
        raw=(assets/url.rsplit('/',1)[1]).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==expected
        return raw
    monkeypatch.setattr(tools,'download',local_download)
    tools.install()
    return isolated


def test_actual_crypto_setup_roundtrip_idempotence_and_restore(actual_tools,capsys):
    root,home,values=actual_tools
    vault.setup();key=vault.identity().read_bytes()
    assert b'AGE-SECRET-KEY-1' in key
    assert not vault.identity().is_relative_to(root)
    assert vault.check()==values
    raw=vault.latest().read_bytes()
    assert all(v not in raw for v in values.values())
    assert b'sk_test_FICTITIOUS_ONLY' not in raw and b'jeton fictif' not in raw
    vault.setup();assert vault.identity().read_bytes()==key
    assert len(list((root/'secrets').glob('*.sops.json')))==2
    vault.restore_test()
    assert not list(tools.secure_home().glob('restore-test-*'))
    assert {n:(root/n).read_bytes() for n in values}==values
    stdout=capsys.readouterr().out
    assert 'AGE-SECRET-KEY-1' not in stdout and 'sk_test_FICTITIOUS_ONLY' not in stdout
    assert 'fictitious-only' not in stdout


def test_actual_crypto_tamper_and_wrong_key_fail_closed(actual_tools):
    root,_,values=actual_tools;vault.setup();p=vault.latest()
    original=p.read_bytes();data=json.loads(original)
    encrypted=data['data'];pos=encrypted.index('data:')+5
    data['data']=encrypted[:pos]+('A' if encrypted[pos]!='A' else 'B')+encrypted[pos+1:]
    p.write_text(json.dumps(data))
    with pytest.raises(perm.SecretError):vault.check()
    p.write_bytes(original)
    # Replace only the fixture key with another valid identity.
    other=vault.run_tool('age-keygen',[]);vault.identity().write_bytes(other)
    with pytest.raises(perm.SecretError):vault.check()
    assert all((root/n).read_bytes()==v for n,v in values.items())


def test_change_detected_then_reseal_without_rotation(actual_tools):
    root,_,values=actual_tools;vault.setup();key=vault.identity().read_bytes()
    (root/'.env').write_bytes(values['.env']+b'NEW_FIXTURE=changed\n')
    with pytest.raises(perm.SecretError):vault.check()
    vault.seal();assert vault.check()['.env'].endswith(b'NEW_FIXTURE=changed\n')
    assert vault.identity().read_bytes()==key


def test_lost_key_is_not_silently_regenerated(actual_tools):
    vault.setup();vault.identity().unlink()
    with pytest.raises(perm.SecretError,match='sans cle'):vault.setup()
    assert not vault.identity().exists()


def test_runtime_missing_refuses_snapshot(actual_tools):
    root,_,_=actual_tools;vault.setup();previous=vault.latest()
    (root/'.camera-agent.json').unlink()
    with pytest.raises(perm.SecretError):vault.seal()
    assert vault.latest()==previous


def test_symlink_credentials_refused(isolated):
    root,home,values=isolated;(root/'.env').unlink()
    outside=home/'secret';outside.write_bytes(b'do not read');(root/'.env').symlink_to(outside)
    with pytest.raises(perm.SecretError):vault.runtime(protect=True)
    assert outside.stat().st_mode & 0o077 != 0


def test_bad_scope_restore_is_rejected_before_writing(isolated):
    root,home,values=isolated
    for target in [root,root/'restore',root.parent]:
        with pytest.raises((perm.SecretError,FileExistsError)):vault.restore_files(values,target)
    output=home/'restore';vault.restore_files(values,output)
    with pytest.raises(FileExistsError):vault.restore_files(values,output)
    assert all((output/n).read_bytes()==v for n,v in values.items())


def test_bad_payload_path_cannot_be_restored(actual_tools,monkeypatch):
    vault.setup();raw=vault.latest().read_bytes()
    public=vault.recipient()
    bundle={'schema':1,'created_at':'now','files':{'../../untrusted':'eA=='}}
    monkeypatch.setattr(vault,'run_tool',lambda *a,**k:json.dumps(bundle).encode())
    with pytest.raises(perm.SecretError,match='invalide'):vault.decrypt(raw,public)


def test_tools_tampered_binary_refused_before_execution(actual_tools):
    tools.tool_path('sops').write_bytes(b'changed binary')
    with pytest.raises(perm.SecretError,match='modifie'):tools.check_tools()


def test_process_does_not_inherit_remote_keyservice_or_secret(isolated,monkeypatch):
    for name in ['SOPS_AGE_KEY','SOPS_KMS_ARN','SOPS_KEYSERVICE','SOPS_AGE_RECIPIENTS','HTTP_PROXY','STRIPE_SECRET_KEY']:
        monkeypatch.setenv(name,'PRIVATE_UNTRUSTED')
    env=vault.tool_environment()
    assert 'PRIVATE_UNTRUSTED' not in json.dumps(env)
    assert 'SOPS_AGE_KEY' not in env and env['SOPS_AGE_KEY_FILE']==str(vault.identity())


def test_source_export_excludes_sensitive_copies_ciphertext_and_links(tmp_path):
    project=tmp_path/'project';(project/'scripts').mkdir(parents=True)
    shutil.copy2(ROOT/'scripts/export_source.py',project/'scripts/export_source.py')
    sensitive=['.env','.env.copy','.camera-agent.json.old','esp8266-led/include/secrets.h.bak-123',
               'secrets/runtime-abc.sops.json','key.age','keys.txt','db.dump',
               'backend/main.py.bak-123','secrets-restore-test/.env',
               '.rearm-backup-test/settings.json','private.key']
    for name in sensitive:
        p=project/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'SENSITIVE_FIXTURE')
    (project/'backend/real.py').write_text('print("source")')
    outside=tmp_path/'external.txt';outside.write_text('SENSITIVE_FIXTURE')
    (project/'linked.txt').symlink_to(outside)
    result=subprocess.run([sys.executable,str(project/'scripts/export_source.py')],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    with ZipFile(tmp_path/'REARM-source.zip') as z:
        assert 'backend/real.py' in z.namelist()
        assert not any(n in z.namelist() for n in sensitive)
        assert 'linked.txt' not in z.namelist()
        assert all(b'SENSITIVE_FIXTURE' not in z.read(n) for n in z.namelist())


def test_permissions_failure_happens_before_writing_plaintext(tmp_path,monkeypatch):
    p=tmp_path/'identity.txt'
    def refused(*a,**kw):raise perm.SecretError('Droits refuses')
    monkeypatch.setattr(vault,'private',refused)
    with pytest.raises(perm.SecretError):vault.write_private(p,b'SENSITIVE_FIXTURE')
    assert not p.exists()


def test_loose_permissions_fail_check_without_mutation(tmp_path):
    p=tmp_path/'fixture';p.write_bytes(b'UNCHANGED');p.chmod(0o644)
    with pytest.raises(perm.SecretError):perm.private(p)
    assert p.read_bytes()==b'UNCHANGED' and p.stat().st_mode & 0o077
    perm.private(p,apply=True)
    assert p.read_bytes()==b'UNCHANGED' and not p.stat().st_mode & 0o077
