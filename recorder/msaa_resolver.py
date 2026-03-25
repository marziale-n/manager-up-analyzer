from __future__ import annotations

import ctypes
import logging
from typing import Any

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

def get_msaa_info(hwnd: int | None) -> dict[str, Any] | None:
    """
    Estrae dati MSAA in modalità 'Safe/Read-Only'.
    Gestisce l'inizializzazione COM per i thread di background per evitare memory leak o blocchi.
    """
    if not HAS_COMTYPES or not hwnd:
        return None

    # FONDAMENTALE: Inizializza il sottosistema COM per questo specifico thread.
    # Evita crash se chiamato dal thread del WinEventMonitor.
    comtypes.CoInitialize()
    
    try:
        oleacc = ctypes.windll.oleacc
        pacc = ctypes.POINTER(Accessibility.IAccessible)()
        
        # OBJID_CLIENT = -4. Punta all'area dati pura, senza toccare scrollbar o bordi.
        OBJID_CLIENT = -4 
        
        # Chiamata passiva (invia WM_GETOBJECT)
        res = oleacc.AccessibleObjectFromWindow(
            hwnd, 
            OBJID_CLIENT, 
            ctypes.byref(Accessibility.IAccessible._iid_), 
            ctypes.byref(pacc)
        )
        
        if res == 0 and pacc:
            # Estrazione puramente passiva dei metadati
            name = pacc.accName(0)
            value = pacc.accValue(0)
            
            if name or value:
                return {
                    "msaa_name": name,
                    "msaa_value": value,
                }
    except Exception as e:
        # Silenziamo qualsiasi errore (es. permessi negati o app crashata) 
        # per non interrompere il recorder principale.
        logging.debug(f"Lettura MSAA fallita o negata per HWND {hwnd}: {e}")
    finally:
        # FONDAMENTALE: Rilascia le risorse COM per evitare leak di memoria nel monitoraggio a lungo termine
        comtypes.CoUninitialize()
        
    return None