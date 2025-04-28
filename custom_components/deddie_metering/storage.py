import homeassistant.util.dt as dt_util
from homeassistant.helpers.storage import Store
from .const import DOMAIN


async def load_last_total(hass, supply: str):
    """
    Φορτώνει το τελευταίο συσσωρευμένο σύνολο κατανάλωσης (last_total)
    από το persistent store για την συγκεκριμένη παροχή.
    """
    store = Store(hass, 1, f"{DOMAIN}_last_total.json")
    data = await store.async_load()
    if data:
        return data.get(f"total_{supply}")
    return None


async def save_last_total(hass, supply: str, total: float):
    """
    Αποθηκεύει το τελευταίο συσσωρευμένο σύνολο κατανάλωσης (last_total)
    στο persistent store για την συγκεκριμένη παροχή.
    """
    store = Store(hass, 1, f"{DOMAIN}_last_total.json")
    data = await store.async_load() or {}
    data[f"total_{supply}"] = total
    await store.async_save(data)


async def load_last_update(hass, supply: str):
    """
    Φορτώνει το timestamp της τελευταίας επιτυχημένης ενημέρωσης (last_update)
    από το persistent store για την συγκεκριμένη παροχή.
    """
    store = Store(hass, 1, f"{DOMAIN}_last_update.json")
    data = await store.async_load()
    if data and f"last_update_{supply}" in data:
        return dt_util.parse_datetime(data[f"last_update_{supply}"])
    return None


async def save_last_update(hass, supply: str, update_dt):
    """
    Αποθηκεύει το timestamp της τελευταίας ενημέρωσης (last_update)
    στο persistent store για την συγκεκριμένη παροχή.
    """
    store = Store(hass, 1, f"{DOMAIN}_last_update.json")
    data = await store.async_load() or {}
    data[f"last_update_{supply}"] = update_dt.isoformat()
    await store.async_save(data)


async def load_initial_jump_flag(hass, supply: str):
    """
    Φορτώνει το flag που δείχνει εάν έχει ήδη πραγματοποιηθεί
    η πρώτη "jump" ενημέρωση για την παροχή.
    """
    store = Store(hass, 1, f"{DOMAIN}_initial_jump.json")
    data = await store.async_load()
    if data:
        return data.get(f"jump_{supply}", False)
    return False


async def save_initial_jump_flag(hass, supply: str, flag: bool):
    """
    Αποθηκεύει το flag που δείχνει εάν έχει ήδη πραγματοποιηθεί
    η πρώτη "jump" ενημέρωση για την παροχή.
    """
    store = Store(hass, 1, f"{DOMAIN}_initial_jump.json")
    data = await store.async_load() or {}
    data[f"jump_{supply}"] = flag
    await store.async_save(data)
