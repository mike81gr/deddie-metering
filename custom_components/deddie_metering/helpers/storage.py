import homeassistant.util.dt as dt_util
from homeassistant.helpers.storage import Store
from ..const import DOMAIN, ATTR_CONSUMPTION


async def load_last_total(hass, supply: str, key: str = ATTR_CONSUMPTION):
    """
    Φορτώνει το τελευταίο συσσωρευμένο σύνολο (last_total) της
    κατανάλωσης/παραγωγής/έγχυσης από το persistent store για
    την συγκεκριμένη παροχή.
    """
    store = Store(hass, 1, f"{DOMAIN}_last_total.json")
    data = await store.async_load()
    if not data:
        return None
    # Περίπτωση fallback για consumption
    if key == ATTR_CONSUMPTION:
        return data.get(f"{key}_total_{supply}") or data.get(f"total_{supply}")
    # Υπόλοιπα keys, production & injection
    return data.get(f"{key}_total_{supply}")


async def save_last_total(hass, supply: str, total: float, key: str = "active"):
    """
    Αποθηκεύει το τελευταίο συσσωρευμένο σύνολο (last_total) της
    κατανάλωσης/παραγωγής/έγχυσης στο persistent store για την
    συγκεκριμένη παροχή.
    """
    store = Store(hass, 1, f"{DOMAIN}_last_total.json")
    data = await store.async_load() or {}
    data[f"{key}_total_{supply}"] = total
    await store.async_save(data)


async def load_last_update(hass, supply: str, key: str = ATTR_CONSUMPTION):
    """
    Φορτώνει το timestamp της τελευταίας επιτυχημένης ενημέρωσης (last_update)
    της κατανάλωσης/παραγωγής/έγχυσης, καθώς και του τελευταίου ελέγχου
    φωτοβολταϊκών από το persistent store για την συγκεκριμένη παροχή.
    """
    store = Store(hass, 1, f"{DOMAIN}_last_update.json")
    data = await store.async_load()
    if not data:
        return None
    field = f"last_update_{key}_{supply}"
    # Περίπτωση fallback για consumption
    if key == ATTR_CONSUMPTION:
        raw = data.get(field) or data.get(f"last_update_{supply}")
    else:
        raw = data.get(field)
    # Υπόλοιπα keys, production & injection
    return dt_util.parse_datetime(raw) if raw else None


async def save_last_update(hass, supply: str, update_dt, key: str = "active"):
    """
    Αποθηκεύει το timestamp της τελευταίας ενημέρωσης (last_update)
    της κατανάλωσης/παραγωγής/έγχυσης στο persistent store για την
    συγκεκριμένη παροχή.
    """
    store = Store(hass, 1, f"{DOMAIN}_last_update.json")
    data = await store.async_load() or {}
    data[f"last_update_{key}_{supply}"] = update_dt.isoformat()
    await store.async_save(data)


async def load_initial_jump_flag(hass, supply: str, key: str = ATTR_CONSUMPTION):
    """
    Φορτώνει το flag που δείχνει εάν έχει ήδη πραγματοποιηθεί
    η πρώτη "jump" ενημέρωση της κατανάλωσης/παραγωγής/έγχυσης
    για την παροχή.
    """
    store = Store(hass, 1, f"{DOMAIN}_initial_jump.json")
    data = await store.async_load()
    if not data:
        return False
    field = f"jump_{key}_{supply}"
    # Περίπτωση fallback για consumption
    if key == ATTR_CONSUMPTION:
        return data.get(field) or data.get(f"jump_{supply}", False)
    # Υπόλοιπα keys, production & injection
    return data.get(field, False)


async def save_initial_jump_flag(hass, supply: str, flag: bool, key: str = "active"):
    """
    Αποθηκεύει το flag που δείχνει εάν έχει ήδη πραγματοποιηθεί
    η πρώτη "jump" ενημέρωση της κατανάλωσης/παραγωγής/έγχυσης
    για την παροχή.
    """
    store = Store(hass, 1, f"{DOMAIN}_initial_jump.json")
    data = await store.async_load() or {}
    data[f"jump_{key}_{supply}"] = flag
    await store.async_save(data)
