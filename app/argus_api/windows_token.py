"""從 IIS 傳入的 Windows token handle 解析登入帳號。

skill 要點：用 GetTokenInformation(TokenUser) + LookupAccountSid 直接讀 SID，
不靠 ImpersonateLoggedOnUser (AppPool 為 LocalSystem 時會拿到 IIS 程序身分)。

僅在 Windows 上運作；其他平台回傳 ""，使 app 仍可於 Linux 開發/測試。
"""
import sys


def username_from_token(token_handle: int) -> str:
    if sys.platform != "win32":
        return ""

    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.windll.advapi32

    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.LookupAccountSidW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_void_p,
        wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD)]
    advapi32.LookupAccountSidW.restype = wintypes.BOOL

    TokenUser = 1
    size = wintypes.DWORD(0)
    advapi32.GetTokenInformation(token_handle, TokenUser, None, 0, ctypes.byref(size))
    if size.value == 0:
        return ""

    buf = ctypes.create_string_buffer(size.value)
    if not advapi32.GetTokenInformation(token_handle, TokenUser, buf, size, ctypes.byref(size)):
        return ""

    psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]

    name = ctypes.create_unicode_buffer(256)
    name_len = wintypes.DWORD(256)
    dom = ctypes.create_unicode_buffer(256)
    dom_len = wintypes.DWORD(256)
    sid_type = wintypes.DWORD()

    if not advapi32.LookupAccountSidW(
        None, psid, name, ctypes.byref(name_len),
        dom, ctypes.byref(dom_len), ctypes.byref(sid_type)
    ):
        return ""

    return name.value
