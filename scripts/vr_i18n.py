"""vr_i18n.py -- minimal shared translation layer for the VR launcher tools.

Scope, deliberately limited tonight: the boot selector's own prompt and
power-on.py's step titles + final verdicts (the messages every user sees
regardless of hardware state). NOT translated yet: the detailed per-step
diagnostic lines (dim()/warn() messages inside each check), vr-launcher.py's
menu, or vr-launcher-console.sh -- those stay Spanish-only until a follow-up
pass. Don't assume full i18n coverage from this file alone.

Language selection: $VR_LANG env var ("es" or "en"), default "es" (matches
this whole project's own convention -- CLAUDE.md: "he speaks Spanish").
"""
import os

LANG = os.environ.get("VR_LANG", "es")
if LANG not in ("es", "en"):
    LANG = "es"

STRINGS = {
    # USB socket verdicts. The technical verdict names controllers and PCI addresses because
    # that is what a later reader needs; THIS is the line for the person standing behind the
    # machine with the cable in their hand, and it must survive being read out loud over the
    # phone. No xHCI, no PCI addresses, no branch names.
    "usb_action_wrong_socket": {
        "es": "Busca un USB AZUL en la parte de atras del gabinete y probá otro. No todos sirven: los de arriba y los de abajo van por caminos distintos adentro de la PC.",
        "en": "Look for a BLUE USB socket on the BACK of the case and try a different one. They are not all equal: the upper and lower ones take different routes inside the PC.",
    },
    "usb_action_usb2_only": {
        "es": "Estas en un USB NEGRO (el lento). Buscá uno AZUL en la parte de atras del gabinete.",
        "en": "You are in a BLACK (slow) USB socket. Look for a BLUE one on the BACK of the case.",
    },
    "usb_action_nothing": {
        "es": "No aparece nada. Fijate que el casco este enchufado a la corriente y que el cable este bien metido de los dos lados.",
        "en": "Nothing shows up. Check that the headset is plugged into mains power and that the cable is firmly seated at both ends.",
    },
    "usb_action_cable": {
        "es": "El puerto esta bien, asi que ahora el sospechoso es el cable. Desenchufá y volvé a enchufar el conector del lado del visor, firme.",
        "en": "The socket is fine, so the cable is the suspect now. Unplug and firmly re-seat the connector at the visor end.",
    },
    # The HP logo is the single most misleading signal in this whole procedure, because it is
    # the first thing a person looks at and it looks like success. It is an ELECTRICALLY LIT
    # marking on the FRONT SHELL of the headset -- outside, visible without wearing it -- not
    # something rendered on the panel. Saying "inside the visor" sends someone to look in the
    # wrong place and conclude the headset is dead when it is merely misplugged. It means the companion has
    # power and the PC could talk to it over HID. It says NOTHING about DisplayPort, about the
    # socket being the right one, or about tracking -- measured 2026-08-19: the logo lit on a
    # USB2-only socket where tracking cannot work.
    "usb_logo_means": {
        "es": "OJO: el logo HP ILUMINADO EN EL FRENTE DEL CASCO (por fuera, no adentro del visor) NO quiere decir que este todo bien. Solo dice que el casco tiene corriente y que la PC le pudo hablar. No dice que el puerto sea el correcto, ni que vaya a haber imagen adentro, ni que el tracking funcione.",
        "en": "CAREFUL: the HP logo LIT ON THE FRONT SHELL of the headset (outside, not inside the visor) does NOT mean things are working. It only means the headset has power and the PC could talk to it. It says nothing about the socket being right, about getting an image inside, or about tracking.",
    },
    # TWO measured levers, each tied to its census signature -- do not swap them (the agent did,
    # 2026-08-20, and it took the user quoting the docs to undo it):
    #   0/5           -> the plug is on the WRONG SIDE. T184, tape-marked A/B: matched
    #                    orientation = 0/5 always, unmatched = at least 2/5. The flip is the
    #                    0/5 lever, nothing else.
    #   2/5, SS only  -> right side, USB2 branch not joined. T186: PC-end USB-C unplug, a cold
    #                    ~8-10 s gap, replug SAME port SAME side = 6/6 clean 5/5, genuine
    #                    re-enumeration. A flip here would land on 0/5.
    "usb_action_flip_plug": {
        "es": "Si el casco tiene corriente y aun asi no aparece NADA, el conector USB-C esta del lado equivocado: sacalo, GIRALO 180 grados y volvé a enchufarlo en el mismo puerto. El lado malo da exactamente cero dispositivos (medido).",
        "en": "If the headset has power and still NOTHING shows up, the USB-C plug is on the wrong side: unplug it, ROTATE IT 180 DEGREES and plug it back into the same port. The wrong side gives exactly zero devices (measured).",
    },
    "usb_action_cold_replug": {
        "es": "El lado del conector es el CORRECTO -- no lo gires. Desenchufá el USB-C del lado de la PC, contá 10 segundos, y volvé a enchufarlo en el MISMO puerto y con el MISMO lado. Ese corte en frío recuperó la rama que falta 6 de 6 veces.",
        "en": "The plug side is CORRECT -- do not flip it. Unplug the USB-C at the PC end, count 10 seconds, and plug it back into the SAME port on the SAME side. That cold gap recovered the missing branch 6 out of 6 times.",
    },
    "usb_action_ok": {
        "es": "Este puerto anda. Dejá el cable acá y no lo muevas.",
        "en": "This socket works. Leave the cable here and do not move it.",
    },
    "boot_selector_title": {
        "es": "HP Reverb G2 -- selector de arranque",
        "en": "HP Reverb G2 -- boot selector",
    },
    "boot_selector_auto": {
        "es": "[a] Auto    -- diagnostico ahora mismo, en consola, sin escritorio",
        "en": "[a] Auto    -- diagnose right now, in the console, no desktop",
    },
    "boot_selector_manual": {
        "es": "[m] Manual  -- arranque normal (login grafico), como siempre",
        "en": "[m] Manual  -- normal boot (graphical login), as usual",
    },
    "power_on_title": {
        "es": "=== Encendiendo el HP Reverb G2 ===",
        "en": "=== Powering on the HP Reverb G2 ===",
    },
    "power_on_subtitle": {
        "es": "Esto corre en tu monitor normal, no en el casco -- todavia no hay nada que ponerte.",
        "en": "This runs on your normal monitor, not the headset -- there's nothing to put on yet.",
    },
    "step_1": {"es": "¿Está todo conectado?", "en": "Is everything connected?"},
    "step_2": {"es": "¿Estás en un puerto que sabemos que funciona?", "en": "Are you on a port known to work?"},
    "step_3": {"es": "¿Las cámaras tienen el ancho de banda que necesitan?", "en": "Do the cameras have the bandwidth they need?"},
    "step_4": {"es": "¿El panel está despierto y es realmente el del G2?", "en": "Is the panel awake and really the G2's?"},
    "step_5": {"es": "¿Los controles están prendidos?", "en": "Are the controllers powered on?"},
    "verdict_title": {"es": "=== Veredicto ===", "en": "=== Verdict ==="},
    "verdict_listo": {"es": "LISTO.", "en": "READY."},
    "verdict_te_necesito": {"es": "TE NECESITO.", "en": "I NEED YOU."},
    "verdict_hay_que_comprar": {"es": "HAY QUE COMPRAR.", "en": "NEED TO BUY."},
}


def t(key):
    """Look up a translated string; falls back to Spanish, then the key
    itself, so a missing translation never crashes the tool -- it just shows
    Spanish (or the raw key as a last resort) instead of blowing up."""
    entry = STRINGS.get(key)
    if not entry:
        return key
    return entry.get(LANG) or entry.get("es") or key
