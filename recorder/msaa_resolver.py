from __future__ import annotations

import ctypes
import logging
from typing import Any, List, Optional, Dict

try:
    import comtypes
    import comtypes.client
    # Forza la generazione del wrapper
    comtypes.client.GetModule("oleacc.dll")
    from comtypes.gen import Accessibility
    HAS_COMTYPES = True
except ImportError:
    logging.warning("Libreria 'comtypes' non trovata. MSAA disabilitato.")
    HAS_COMTYPES = False

# Costanti MSAA
OBJID_CLIENT = -4
STATE_SYSTEM_INVISIBLE = 0x00008000
ROLE_SYSTEM_CELL = 0x1D
ROLE_SYSTEM_COLUMNHEADER = 0x19
ROLE_SYSTEM_ROWHEADER = 0x1A

def get_msaa_info(hwnd: int | None) -> dict[str, Any] | None:
    """
    Estrae dati MSAA in modalità 'Safe/Read-Only'.
    Gestisce l'inizializzazione COM per i thread di background per evitare memory leak o blocchi.
    """
    if not HAS_COMTYPES or not hwnd:
        return None

    comtypes.CoInitialize()
    
    try:
        oleacc = ctypes.windll.oleacc
        pacc = ctypes.POINTER(Accessibility.IAccessible)()
        
        res = oleacc.AccessibleObjectFromWindow(
            hwnd, 
            OBJID_CLIENT, 
            ctypes.byref(Accessibility.IAccessible._iid_), 
            ctypes.byref(pacc)
        )
        
        if res == 0 and pacc:
            name = pacc.accName(0)
            value = pacc.accValue(0)
            
            if name or value:
                return {
                    "msaa_name": name,
                    "msaa_value": value,
                }
    except Exception as e:
        logging.debug(f"Lettura MSAA fallita per HWND {hwnd}: {e}")
    finally:
        comtypes.CoUninitialize()
        
    return None

def get_msaa_grid_data(hwnd: int | None, max_cells: int = 200) -> List[Dict[str, Any]] | None:
    """
    Estrae ricorsivamente i dati delle celle da un controllo griglia usando MSAA.
    """
    if not HAS_COMTYPES or not hwnd:
        return None

    comtypes.CoInitialize()
    cells = []
    
    try:
        oleacc = ctypes.windll.oleacc
        pacc = ctypes.POINTER(Accessibility.IAccessible)()
        
        res = oleacc.AccessibleObjectFromWindow(
            hwnd, 
            OBJID_CLIENT, 
            ctypes.byref(Accessibility.IAccessible._iid_), 
            ctypes.byref(pacc)
        )
        
        if res == 0 and pacc:
            _extract_accessible_children(pacc, cells, max_cells)
    except Exception as e:
        logging.debug(f"Scansione Grid MSAA fallita per HWND {hwnd}: {e}")
    finally:
        comtypes.CoUninitialize()
        
    return cells if cells else None

def _extract_accessible_children(pacc: Any, results: List[Dict[str, Any]], max_items: int):
    if len(results) >= max_items:
        return

    count = pacc.accChildCount
    if count <= 0:
        return

    # Preparazione per AccessibleChildren
    children = (ctypes.c_variant * count)()
    obtained = ctypes.c_long()
    
    if ctypes.windll.oleacc.AccessibleChildren(pacc, 0, count, children, ctypes.byref(obtained)) == 0:
        for i in range(obtained.value):
            if len(results) >= max_items:
                break
                
            child_variant = children[i]
            
            # Se VT_DISPATCH (9), il figlio è un altro oggetto IAccessible
            if child_variant.vt == 9:
                child_pacc = child_variant.value.QueryInterface(Accessibility.IAccessible)
                
                # Prova a estrarre dati se è una cella o simile
                role = child_pacc.accRole(0)
                name = child_pacc.accName(0)
                value = child_pacc.accValue(0)
                state = child_pacc.accState(0)
                
                # Filtra elementi invisibili se non sono celle
                if not (state & STATE_SYSTEM_INVISIBLE) or role in (ROLE_SYSTEM_CELL, ROLE_SYSTEM_COLUMNHEADER):
                    if name or value:
                        results.append({
                            "name": name,
                            "value": value,
                            "role": role,
                            "state": state
                        })
                
                # Ricorsione se non è già una cella (le celle di solito non hanno figli utili)
                if role not in (ROLE_SYSTEM_CELL, ROLE_SYSTEM_COLUMNHEADER, ROLE_SYSTEM_ROWHEADER):
                    _extract_accessible_children(child_pacc, results, max_items)
            
            # Se VT_I4 (3), il figlio è un Child ID semplice dell'oggetto corrente
            elif child_variant.vt == 3:
                child_id = child_variant.value
                role = pacc.accRole(child_id)
                name = pacc.accName(child_id)
                value = pacc.accValue(child_id)
                state = pacc.accState(child_id)
                
                if not (state & STATE_SYSTEM_INVISIBLE):
                    if name or value:
                        results.append({
                            "name": name,
                            "value": value,
                            "role": role,
                            "state": state,
                            "child_id": child_id
                        })