"""純 stdlib 的 AD 輔助函式 — 無第三方相依，可離線單元測試。"""
import base64
import struct


def derive_base_dn(domain: str) -> str:
    """由網域推導 LDAP Base DN。

    skill 規則：把網域以 '.' 拆開，每段加 'DC='，逗號合併。
    'kh.asegroup.com' -> 'DC=kh,DC=asegroup,DC=com'
    """
    parts = [p for p in domain.strip().split(".") if p]
    return ",".join(f"DC={p}" for p in parts)


def parse_ntlm_username(auth_header: str) -> str:
    """從 NTLM Type-3 訊息解出帳號名 (固定 offset，純 Python，不需 Windows API)。"""
    try:
        data = base64.b64decode(auth_header.split(" ", 1)[-1].strip())
        if len(data) < 44 or struct.unpack_from("<I", data, 8)[0] != 3:
            return ""
        un_len = struct.unpack_from("<H", data, 36)[0]
        un_offset = struct.unpack_from("<I", data, 40)[0]
        return data[un_offset: un_offset + un_len].decode("utf-16-le")
    except Exception:
        return ""
