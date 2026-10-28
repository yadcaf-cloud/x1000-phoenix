def statut_fige(document):
    """Classer un FIGÉ sans modifier son contenu historique."""
    verifier_fige(document)
    rapport = rapport_fige(document)

    moteurs = rapport.get("moteurs", [])
    if not isinstance(moteurs, list):
        raise ValueError("Liste des moteurs FIGÉS invalide")

    officiels = [
        moteur
        for moteur in moteurs
        if isinstance(moteur, dict)
        and moteur.get("validation") == "OFFICIEL_VALIDE"
        and moteur.get("pari_retenu") is not None
        and moteur.get("pari_retenu") != ""
    ]

    if officiels:
        return "PARI_OFFICIEL_FIGE"

    return "FIGE_INDICATIF"


def chemin_fige(course_id):
    """Retourner le chemin du FIGÉ associé à une course."""
    return FIGES / (identifiant(course_id) + ".json")
