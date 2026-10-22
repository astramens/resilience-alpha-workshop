"""Restrict credentials to the current user (+ SYSTEM on Windows), verify exactly.

No shell or translated account names. Windows uses SID-based protected DACLs.
"""
import os
import stat
from pathlib import Path


class SecretError(Exception):
    pass


def no_links(path):
    path = Path(path).absolute()
    for p in (path, *path.parents):
        if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
            raise SecretError('Lien ou jonction refuse pour les fichiers sensibles.')
    return path


class WindowsACL:
    def __init__(self):
        import ctypes as c
        from ctypes import wintypes as w
        self.c, self.w = c, w
        self.a = c.WinDLL('advapi32', use_last_error=True)
        self.k = c.WinDLL('kernel32', use_last_error=True)
        P = c.c_void_p; PP = c.POINTER(P)
        signatures = [
            ('OpenProcessToken', [w.HANDLE,w.DWORD,c.POINTER(w.HANDLE)],w.BOOL),
            ('GetTokenInformation',[w.HANDLE,w.DWORD,P,w.DWORD,c.POINTER(w.DWORD)],w.BOOL),
            ('ConvertSidToStringSidW',[P,c.POINTER(w.LPWSTR)],w.BOOL),
            ('ConvertStringSecurityDescriptorToSecurityDescriptorW',[w.LPCWSTR,w.DWORD,PP,c.POINTER(w.DWORD)],w.BOOL),
            ('GetSecurityDescriptorDacl',[P,c.POINTER(w.BOOL),PP,c.POINTER(w.BOOL)],w.BOOL),
            ('GetSecurityDescriptorControl',[P,c.POINTER(w.WORD),c.POINTER(w.DWORD)],w.BOOL),
            ('SetNamedSecurityInfoW',[w.LPWSTR,w.DWORD,w.DWORD,P,P,P,P],w.DWORD),
            ('GetNamedSecurityInfoW',[w.LPWSTR,w.DWORD,w.DWORD,PP,PP,PP,PP,PP],w.DWORD),
            ('GetAce',[P,w.DWORD,PP],w.BOOL),
        ]
        for name,args,result in signatures:
            f=getattr(self.a,name);f.argtypes=args;f.restype=result
        self.k.GetCurrentProcess.argtypes=[];self.k.GetCurrentProcess.restype=w.HANDLE
        self.k.CloseHandle.argtypes=[w.HANDLE];self.k.CloseHandle.restype=w.BOOL
        self.k.LocalFree.argtypes=[P];self.k.LocalFree.restype=P

    def sid_string(self, sid):
        c,w=self.c,self.w;value=w.LPWSTR()
        if not self.a.ConvertSidToStringSidW(sid,c.byref(value)):
            raise SecretError('Lecture SID impossible.')
        try:return value.value
        finally:self.k.LocalFree(c.cast(value,c.c_void_p))

    def user_sid(self):
        c,w=self.c,self.w;token=w.HANDLE();size=w.DWORD()
        if not self.a.OpenProcessToken(self.k.GetCurrentProcess(),8,c.byref(token)):
            raise SecretError('Lecture du compte Windows impossible.')
        try:
            self.a.GetTokenInformation(token,1,None,0,c.byref(size))
            buf=c.create_string_buffer(size.value)
            if not self.a.GetTokenInformation(token,1,buf,size.value,c.byref(size)):
                raise SecretError('Lecture du compte Windows impossible.')
            return self.sid_string(c.cast(buf,c.POINTER(c.c_void_p))[0])
        finally:self.k.CloseHandle(token)

    def protect(self, path):
        c,w=self.c,self.w;sd=c.c_void_p();dacl=c.c_void_p()
        present=w.BOOL();defaulted=w.BOOL()
        flags='OICI' if path.is_dir() else ''
        sddl='D:P(A;'+flags+';FA;;;SY)(A;'+flags+';FA;;;'+self.user_sid()+')'
        if not self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl,1,c.byref(sd),None):
            raise SecretError('Creation de la protection Windows impossible.')
        try:
            if not self.a.GetSecurityDescriptorDacl(sd,c.byref(present),c.byref(dacl),c.byref(defaulted)) or not present.value or not dacl.value:
                raise SecretError('Protection Windows invalide.')
            if self.a.SetNamedSecurityInfoW(str(path),1,0x80000004,None,None,dacl,None):
                raise SecretError('Application des droits Windows impossible.')
        finally:self.k.LocalFree(sd)

    def verified(self, path):
        c,w=self.c,self.w;sd=c.c_void_p();dacl=c.c_void_p()
        if self.a.GetNamedSecurityInfoW(str(path),1,4,None,None,c.byref(dacl),None,c.byref(sd)):
            return False
        try:
            control=w.WORD();revision=w.DWORD()
            if not self.a.GetSecurityDescriptorControl(sd,c.byref(control),c.byref(revision)) or not control.value & 0x1000 or not dacl.value:
                return False
            # ACL header: revision, reserved, size, ACE count, reserved.
            count=int.from_bytes(c.string_at(dacl,8)[4:6],'little')
            if count != 2:return False
            found=set();expected_flags=3 if path.is_dir() else 0
            for index in range(count):
                ace=c.c_void_p()
                if not self.a.GetAce(dacl,index,c.byref(ace)):return False
                header=c.string_at(ace,8)
                if header[0]!=0 or header[1]!=expected_flags or int.from_bytes(header[4:8],'little')!=0x1f01ff:
                    return False
                found.add(self.sid_string(ace.value+8))
            return found=={self.user_sid(),'S-1-5-18'}
        finally:self.k.LocalFree(sd)


def private(path, apply=False):
    path=no_links(path)
    info=path.stat()
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise SecretError('Type de fichier sensible refuse.')
    if os.name=='nt':
        api=WindowsACL()
        if apply:api.protect(path)
        ok=api.verified(path)
    else:
        if apply:path.chmod(0o700 if path.is_dir() else 0o600)
        info=path.stat()
        ok=info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)==(0o700 if path.is_dir() else 0o600)
    if not ok:raise SecretError('Droits prives non confirmes. Aucun contenu secret affiche.')
    return path


def private_directory(path):
    path=no_links(path);path.mkdir(parents=True,exist_ok=True,mode=0o700)
    return private(path,apply=True)
