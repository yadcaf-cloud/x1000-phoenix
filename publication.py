#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX — collecte, analyses M1-M5 et publication traçable."""

import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from pmu_engine import collecter
from phoenix import DATA, FIGES, analyser, figer, lire, ecrire, verifier_fige

PARIS = ZoneInfo("Europe/Paris")
MOTEURS = ("M1", "M2", "M3", "M4", "M5")


def maintenant():
    return dt.datetime.now(PARIS).isoformat()


def charger(nom, cle, erreurs):
    chemin = DATA / (nom + ".json")
    if not chemin.exists():
        return []
    try:
        objet = lire(chemin)
        if isinstance(objet, list):
            return objet
        if isinstance(objet, dict) and isinstance(objet.get(cle), list):
            return objet[cle]
        raise ValueError("Collection JSON incorrecte")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        erreurs.append(f"{chemin}: {exc}")
        return []


def documents(dossier, erreurs, verifier=False):
    resultat = []
    for chemin in sorted((DATA / dossier).glob("*.json")):
        try:
            objet = lire(chemin)
            if not isinstance(objet, dict):
                raise ValueError("Document JSON non objet")
            if verifier:
                verifier_fige(objet)
            resultat.append(objet)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            erreurs.append(f"{chemin}: {exc}")
    return resultat


def rapport_fige(document):
    if isinstance(document.get("rapport"), dict):
        return document["rapport"]
    contenu = document.get("contenu")
    if isinstance(contenu, dict) and isinstance(contenu.get("analyse"), dict):
        return contenu["analyse"]
    raise ValueError("Format FIGE inconnu")


def moteurs_site(moteurs):
    if not isinstance(moteurs, list):
        return []
    resultat = []
    for moteur in moteurs:
        if not isinstance(moteur, dict) or moteur.get("moteur") not in MOTEURS:
            continue
        copie = dict(moteur)
        if "ordre_espere" not in copie and isinstance(copie.get("ordre"), list):
            copie["ordre_espere"] = copie["ordre"][:5]
        if not isinstance(copie.get("ordre_espere"), list):
            copie["ordre_espere"] = []
        copie["ordre_arrivee_espere"] = copie["ordre_espere"]
        resultat.append(copie)
    return resultat


def unique(objets, cle):
    resultat, vus = [], set()
    for objet in objets:
        if not isinstance(objet, dict):
            continue
        valeur = objet.get(cle)
        if valeur is None or not isinstance(valeur, (str, int)) or valeur in vus:
            continue
        vus.add(valeur)
        resultat.append(objet)
    return resultat


def charger_figes(erreurs):
    figes = documents("figes", erreurs, verifier=True)
    for document in charger("figes", "figes", erreurs):
        try:
            verifier_fige(document)
            figes.append(document)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            erreurs.append(f"FIGE historique invalide: {exc}")
    return unique(figes, "sha256")


def charger_audits(erreurs, figes):
    empreintes = {f["sha256"] for f in figes}
    candidats = documents("audits", erreurs) + charger("audits", "audits", erreurs)
    resultat = []
    for audit in candidats:
        if not isinstance(audit, dict):
            continue
        arrivee = audit.get("arrivee_officielle")
        if (audit.get("statut") == "AUDIT_EFFECTUE"
            and audit.get("fige_sha256") in empreintes
            and isinstance(audit.get("source_arrivee") or audit.get("source_resultat"), str)
            and (audit.get("source_arrivee") or audit.get("source_resultat", "")).startswith("https://")
            and isinstance(arrivee, list)
            and len(arrivee) >= 5
            and all(type(n) is int and n > 0 for n in arrivee)
            and len(set(arrivee)) == len(arrivee)):
            resultat.append(audit)
        else:
            erreurs.append(f"Audit non publie (verification insuffisante): {audit.get('course_id', '?')}")
    return unique(resultat, "fige_sha256")


def construire_pronostics(courses):
    """Une ligne par moteur et par course, sans inventer de selection."""
    resultat = []
    for course in courses:
        for moteur in moteurs_site(course.get("moteurs", [])):
            entree = dict(moteur)
            entree.update({
                "course_id": course.get("id"),
                "hippodrome": course.get("hippodrome"),
                "depart": course.get("depart"),
                "source": course.get("source"),
                "statut_course": course.get("statut"),
            })
            resultat.append(entree)
    return resultat


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    FIGES.mkdir(parents=True, exist_ok=True)
    erreurs = []
    collecte = {}
    courses_brutes = []

    try:
        collecte = collecter()
        if not isinstance(collecte, dict):
            raise ValueError("Collecte non objet")
        courses_brutes = collecte.get("courses", [])
        if not isinstance(courses_brutes, list):
            raise ValueError("Liste de courses invalide")
        erreurs.extend(str(x) for x in collecte.get("erreurs", []))
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        erreurs.append(f"Collecte PMU indisponible: {exc}")
        collecte, courses_brutes = {}, []

    courses, pv = [], []
    for course in courses_brutes:
        if not isinstance(course, dict) or not course.get("id"):
            erreurs.append("Course invalide ou sans identifiant")
            continue
        cid = course["id"]
        ligne = dict(course)
        ligne["statut"] = "DONNEES_NON_ANALYSEES"
        try:
            analyse = analyser(course)
            ligne["moteurs"] = moteurs_site(analyse.get("moteurs", []))
            ligne["analyse_a"] = analyse.get("analyse_a")
            ligne["statut"] = "ANALYSE_INDICATIVE"
            entree = {
                "pv_id": "ANALYSE-" + str(cid),
                "course_id": cid,
                "type": "PV_ANALYSE",
                "statut": "PV_ANALYSE_NON_FIGE",
                "cree_a": analyse.get("analyse_a"),
                "depart": analyse.get("depart"),
                "source": analyse.get("source"),
                "moteurs": ligne["moteurs"],
            }
            document = figer(analyse)
            if document is not None:
                verifier_fige(document)
                entree["statut"] = "FIGE_VERIFIE"
                entree["sha256"] = document["sha256"]
                ligne["statut"] = "FIGE_VERIFIE"
            pv.append(entree)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            erreurs.append(f"{cid}: analyse non disponible: {exc}")
        courses.append(ligne)

    figes = charger_figes(erreurs)
    pv = unique(pv + charger("pv", "pv", erreurs), "pv_id")
    audits = charger_audits(erreurs, figes)

    index = {c["id"]: c for c in courses if c.get("id")}
    for document in figes:
        analyse = rapport_fige(document)
        cid = analyse.get("course_id")
        if not cid:
            continue
        if cid not in index:
            ligne = {
                "id": cid,
                "hippodrome": analyse.get("hippodrome"),
                "depart": analyse.get("depart"),
                "source": analyse.get("source"),
                "nombre_partants": analyse.get("nombre_partants"),
                "moteurs": moteurs_site(analyse.get("moteurs", [])),
                "statut": "FIGE_VERIFIE",
                "localisation_france_verifiee": False,
            }
            courses.append(ligne)
            index[cid] = ligne
        else:
            index[cid]["moteurs"] = moteurs_site(analyse.get("moteurs", []))
            index[cid]["statut"] = "FIGE_VERIFIE"

    pronostics = construire_pronostics(courses)
    analyses_count = sum(bool(c.get("moteurs")) for c in courses)
    if not courses:
        statut = "DONNEES_INDISPONIBLES"
    elif not analyses_count:
        statut = "COURSES_SANS_ANALYSES"
    elif erreurs:
        statut = "PUBLICATION_PARTIELLE"
    else:
        statut = "PUBLICATION_OK"

    rapport = {
        "logiciel": "X1000 PHOENIX",
        "version": "PUBLICATION-UNIFIEE-6.0",
        "status": statut,
        "generated_at_paris": maintenant(),
        "moteurs_actifs": list(MOTEURS),
        "source_donnees": collecte.get("source"),
        "courses_collectees": len(courses_brutes),
        "courses_count": len(courses),
        "analyses_count": analyses_count,
        "pronostics_count": len(pronostics),
        "pv_count": len(pv),
        "figes_count": len(figes),
        "audits_count": len(audits),
        "difficultes": [{"moteur": "SYSTEME", "difficulte": x} for x in erreurs],
        "avertissement": "Aucune course inventee. FIGES originaux conserves. Analyses indicatives non garanties.",
    }

    for nom, cle, objets in (
        ("courses", "courses", courses),
        ("pronostics", "pronostics", pronostics),
        ("pv", "pv", pv),
        ("figes", "figes", figes),
        ("audits", "audits", audits),
    ):
        ecrire(DATA / f"publication_{nom}.json", {cle: objets})

    ecrire(DATA / "publication_rapport.json", rapport)
    ecrire(DATA / "rapport_actions.json", rapport)
    print(json.dumps(rapport, ensure_ascii=False, indent=2))
    return rapport


if __name__ == "__main__":
    main()
