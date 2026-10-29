
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
X1000 PHOENIX - FIGES ET AUDITS M1-M5
VERSION UNIFIEE SECURISEE - 2026-10-29

Compatible avec phoenix.py existant.

PRINCIPES :
- Aucun pronostic retroactif.
- Aucun FIGE historique modifie.
- Aucun resultat officiel invente.
- Controle SHA256 obligatoire.
- Conservation des audits historiques.
- Detection des arrivees contradictoires.
- Publication JSON securisee.
- Aucune certification de source non verifiee.
"""

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from phoenix import (
    DATA,
    FIGES,
    MOTEURS,
    lire,
    ecrire,
    verifier_fige,
    controle_fige,
    rapport_fige,
    maintenant,
)

AUDITS = DATA / "audits"

VERSION = "X1000-PHOENIX-FIGES-AUDITS-7.0"


# ==================================================
# VALIDATION DES SOURCES
# ==================================================

def source_valide(source):
    """
    Verifier la structure HTTPS.

    ATTENTION :
    Une URL HTTPS ne prouve pas que
    son contenu est officiel.
    """

    if not isinstance(source, str):
        return False

    try:
        url = urlparse(source.strip())

        return (
            url.scheme == "https"
            and bool(url.hostname)
            and not url.username
            and not url.password
            and not url.fragment
        )

    except ValueError:
        return False


# ==================================================
# VALIDATION DES ARRIVEES
# ==================================================

def arrivee_valide(ordre):

    if not isinstance(ordre, list):
        return False

    if len(ordre) < 5:
        return False

    if not all(
        type(numero) is int and numero > 0
        for numero in ordre
    ):
        return False

    if len(set(ordre)) != len(ordre):
        return False

    return True


# ==================================================
# LECTURE DES COLLECTIONS
# ==================================================

def charger_collection(nom, cle, erreurs):

    chemin = DATA / nom

    if not chemin.exists():
        return []

    try:
        objet = lire(chemin)

        if isinstance(objet, list):
            return objet

        if isinstance(objet, dict):

            valeur = objet.get(cle, [])

            if isinstance(valeur, list):
                return valeur

        raise ValueError(
            "Collection JSON incorrecte"
        )

    except (
        OSError,
        ValueError,
        TypeError,
        KeyError
    ) as exc:

        erreurs.append(
            f"{chemin}: {exc}"
        )

        return []


# ==================================================
# LECTURE DES DOCUMENTS
# ==================================================

def charger_documents(dossier, erreurs):

    resultat = []

    if not dossier.exists():
        return resultat

    for chemin in sorted(
        dossier.glob("*.json")
    ):

        try:

            document = lire(chemin)

            if not isinstance(document, dict):
                raise ValueError(
                    "Document JSON non objet"
                )

            resultat.append(document)

        except (
            OSError,
            ValueError,
            TypeError
        ) as exc:

            erreurs.append(
                f"{chemin}: {exc}"
            )

    return resultat


# ==================================================
# CHARGEMENT SECURISE DES FIGES
# ==================================================

def charger_figes(erreurs):

    candidats = charger_documents(
        FIGES, erreurs
    )

    candidats += charger_collection(
        "figes.json",
        "figes",
        erreurs
    )

    resultat = []
    empreintes = set()

    for document in candidats:

        try:

            verifier_fige(document)

            controle = controle_fige(document)

            if controle["integrite"] != "VERIFIE":

                erreurs.append(
                    "FIGE non verifiable: "
                    + controle["message"]
                )

                continue

            sha = document["sha256"].lower()

            if sha in empreintes:
                continue

            empreintes.add(sha)

            resultat.append(document)

        except (
            ValueError,
            TypeError,
            KeyError
        ) as exc:

            erreurs.append(
                "FIGE rejete: " + str(exc)
            )

    return resultat


# ==================================================
# CHARGEMENT DES ARRIVEES
# ==================================================

def charger_arrivees(erreurs):

    resultat = {}
    conflits = set()

    chemins = [
        DATA / "arrivees_officielles.json",
        DATA / "publication_arrivees.json",
    ]

    for chemin in chemins:

        if not chemin.exists():
            continue

        try:

            objet = lire(chemin)

            if isinstance(objet, list):
                lignes = objet

            elif isinstance(objet, dict):

                lignes = objet.get(
                    "courses",
                    objet.get("arrivees", [])
                )

            else:
                raise ValueError(
                    "Format des arrivees incorrect"
                )

            if not isinstance(lignes, list):
                raise ValueError(
                    "Liste des arrivees incorrecte"
                )

            for ligne in lignes:

                if not isinstance(ligne, dict):
                    continue

                cid = ligne.get(
                    "course_id",
                    ligne.get("id")
                )

                if cid is None:
                    continue

                cid = str(cid).strip()

                if not cid:
                    continue

                if cid in conflits:
                    continue

                if ligne.get("statut") != "definitive":
                    continue

                source = ligne.get("source")
                ordre = ligne.get("arrivee")

                if not source_valide(source):

                    erreurs.append(
                        f"{cid}: source HTTPS invalide"
                    )

                    continue

                if not arrivee_valide(ordre):

                    erreurs.append(
                        f"{cid}: arrivee invalide"
                    )

                    continue

                candidat = {
                    "course_id": cid,
                    "statut": "definitive",
                    "source": source,
                    "arrivee": ordre,
                }

                if cid in resultat:

                    ancien = resultat[cid]

                    if ancien["arrivee"] != ordre:

                        erreurs.append(
                            f"{cid}: arrivees contradictoires"
                        )

                        conflits.add(cid)
                        resultat.pop(cid, None)

                    continue

                resultat[cid] = candidat

        except (
            OSError,
            ValueError,
            TypeError
        ) as exc:

            erreurs.append(
                f"{chemin}: {exc}"
            )

    return resultat


# ==================================================
# CHARGEMENT DES AUDITS HISTORIQUES
# ==================================================

def charger_audits_existants(figes, erreurs):

    candidats = charger_documents(
        AUDITS, erreurs
    )

    candidats += charger_collection(
        "audits.json",
        "audits",
        erreurs
    )

    candidats += charger_collection(
        "publication_audits.json",
        "audits",
        erreurs
    )

    empreintes = {
        document["sha256"].lower()
        for document in figes
    }

    resultat = []
    vus = set()

    for audit in candidats:

        if not isinstance(audit, dict):
            continue

        sha = audit.get("fige_sha256")

        if not isinstance(sha, str):

            erreurs.append(
                "Audit sans empreinte FIGE"
            )

            continue

        if sha.lower() not in empreintes:

            erreurs.append(
                "Audit sans FIGE verifie: " + sha
            )

            continue

        source = (
            audit.get("source_arrivee")
            or audit.get("source_resultat")
        )

        ordre = audit.get(
            "arrivee_officielle"
        )

        if not source_valide(source):

            erreurs.append(
                "Audit sans source HTTPS valide"
            )

            continue

        if not arrivee_valide(ordre):

            erreurs.append(
                "Audit sans arrivee valide"
            )

            continue

        if audit.get("statut") != "AUDIT_EFFECTUE":

            erreurs.append(
                "Audit sans statut final"
            )

            continue

        cle = json.dumps(
            audit,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False
        )

        if cle in vus:
            continue

        vus.add(cle)

        resultat.append(audit)

    return resultat


# ==================================================
# CONTROLE DES COURSES
# ==================================================

def controle_courses(figes, arrivees):

    attentes = []
    candidats = []

    for document in figes:

        rapport = rapport_fige(document)

        cid = str(
            rapport["course_id"]
        )

        if cid not in arrivees:

            attentes.append(cid)

        else:

            candidats.append(cid)

    return (
        sorted(set(attentes)),
        sorted(set(candidats))
    )


# ==================================================
# CONTROLE DES AUDITS
# ==================================================

def verifier_audits(audits, figes, erreurs):

    index_figes = {
        document["sha256"].lower(): document
        for document in figes
    }

    resultat = []

    for audit in audits:

        try:

            sha = audit["fige_sha256"].lower()

            fige = index_figes.get(sha)

            if fige is None:
                raise ValueError(
                    "FIGE correspondant absent"
                )

            rapport = rapport_fige(fige)

            cid = str(
                rapport["course_id"]
            )

            audit_cid = audit.get("course_id")

            if (
                audit_cid is not None
                and str(audit_cid) != cid
            ):
                raise ValueError(
                    "Identifiant de course incoherent"
                )

            if not arrivee_valide(
                audit["arrivee_officielle"]
            ):
                raise ValueError(
                    "Arrivee incorrecte"
                )

            resultat.append(audit)

        except (
            ValueError,
            KeyError,
            TypeError
        ) as exc:

            erreurs.append(
                "Audit rejete: " + str(exc)
            )

    return resultat


# ==================================================
# PUBLICATION
# ==================================================

def publier():

    DATA.mkdir(
        parents=True,
        exist_ok=True
    )

    FIGES.mkdir(
        parents=True,
        exist_ok=True
    )

    AUDITS.mkdir(
        parents=True,
        exist_ok=True
    )

    erreurs = []

    figes = charger_figes(erreurs)

    arrivees = charger_arrivees(erreurs)

    audits = charger_audits_existants(
        figes,
        erreurs
    )

    audits = verifier_audits(
        audits,
        figes,
        erreurs
    )

    attentes, candidats = controle_courses(
        figes,
        arrivees
    )

    # Les originaux historiques restent intacts.
    # Seules les publications derivees changent.

    ecrire(
        DATA / "publication_figes.json",
        {
            "figes": figes
        }
    )

    ecrire(
        DATA / "publication_audits.json",
        {
            "audits": audits
        }
    )

    rapport = {
        "logiciel": "X1000 PHOENIX",
        "version": VERSION,
        "module": "FIGES_AUDITS_M1_M5",
        "genere_a_paris": maintenant(),
        "moteurs": list(MOTEURS),
        "figes_valides": len(figes),
        "audits_valides": len(audits),
        "arrivees_disponibles": len(arrivees),
        "en_attente_arrivee": attentes,
        "candidats_a_verification": candidats,
        "nouveaux_audits": 0,
        "erreurs": erreurs,
        "statut": (
            "ERREURS_A_VERIFIER"
            if erreurs
            else "AUDITS_HISTORIQUES_DISPONIBLES"
            if audits
            else "FIGES_DISPONIBLES"
            if figes
            else "AUCUN_FIGE_VERIFIE"
        ),
        "note": (
            "FIGES historiques conserves. "
            "Aucun pronostic retroactif. "
            "Aucune arrivee inventee. "
            "Les sources externes ne sont "
            "pas certifiees par ce module."
        ),
    }

    ecrire(
        DATA / "publication_controle_figes_audits.json",
        rapport
    )

    print(
        json.dumps(
            rapport,
            ensure_ascii=False,
            indent=2
        )
    )

    return rapport


# ==================================================
# EXECUTION
# ==================================================

def main():

    try:

        rapport = publier()

        print(
            "X1000 PHOENIX - "
            "CONTROLE FIGES/AUDITS TERMINE"
        )

        print(
            "FIGES VALIDES:",
            rapport["figes_valides"]
        )

        print(
            "AUDITS VALIDES:",
            rapport["audits_valides"]
        )

        print(
            "ERREURS:",
            len(rapport["erreurs"])
        )

        return 0

    except Exception as exc:

        print(
            "ERREUR FIGES/AUDITS: "
            + str(exc),
            file=sys.stderr
        )

        return 1


if __name__ == "__main__":
    sys.exit(main())
