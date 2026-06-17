"""AD 密碼驗證與使用者資訊查詢。

- 密碼驗證用 SIMPLE bind，不用 NTLM (Python 3.9+/OpenSSL 3.0 停用 MD4 會炸)。
- ldap3 延遲匯入，使本模組在未安裝 ldap3 時仍可被匯入 (mock 模式 / 測試)。
"""
from . import config


def _netbios() -> str:
    return (config.AD_SERVER.replace("ldap://", "").replace("ldaps://", "")
            .split("/")[0].upper())


def verify_ad_password(samaccount: str, password: str) -> bool:
    """以 SIMPLE bind 驗證帳號密碼；bind 成功代表密碼正確。"""
    if config.MOCK_AD:
        return bool(samaccount) and password == "mock"

    from ldap3 import Server, Connection, NONE, SIMPLE

    user_str = f"{_netbios()}\\{samaccount}"
    try:
        server = Server(config.AD_SERVER, get_info=NONE)
        conn = Connection(server, user=user_str, password=password,
                          authentication=SIMPLE, auto_bind=True)
        conn.unbind()
        return True
    except Exception:
        return False


def get_ad_user_info(samaccount: str) -> dict:
    """查詢使用者顯示名稱 / email / 部門 / 群組 (需服務帳號)。"""
    if config.MOCK_AD:
        return {"samaccount": samaccount, "displayName": samaccount,
                "email": f"{samaccount}@example.local", "department": "DEV",
                "title": "Engineer", "groups": list(config.MOCK_AD_GROUPS)}

    if not (config.AD_BIND_DN and config.AD_BIND_PW):
        # 沒有服務帳號：只回帳號名，不查群組。
        return {"samaccount": samaccount, "displayName": samaccount,
                "email": "", "department": "", "title": "", "groups": []}

    from ldap3 import Server, Connection, NONE, SIMPLE, SUBTREE

    bind_user = config.AD_BIND_DN
    if not any(c in bind_user for c in ("\\", "@", ",")):
        bind_user = f"{_netbios()}\\{bind_user}"

    base_dn = config.AD_BASE_DN
    server = Server(config.AD_SERVER, get_info=NONE)
    conn = Connection(server, user=bind_user, password=config.AD_BIND_PW,
                      authentication=SIMPLE, auto_bind=True)
    conn.search(base_dn, f"(sAMAccountName={samaccount})", search_scope=SUBTREE,
                attributes=["sAMAccountName", "cn", "displayName",
                            "mail", "department", "title", "memberOf"])
    if not conn.entries:
        conn.unbind()
        return {}

    e = conn.entries[0]
    name = str(e.displayName) if e.displayName else str(e.cn)
    groups = [g.split(",")[0].replace("CN=", "") for g in (e.memberOf.values or [])]
    conn.unbind()
    return {"samaccount": str(e.sAMAccountName), "displayName": name,
            "email": str(e.mail), "department": str(e.department),
            "title": str(e.title), "groups": groups}


def user_in_groups(samaccount: str, groups) -> bool:
    info = get_ad_user_info(samaccount)
    return any(g in info.get("groups", []) for g in groups)
