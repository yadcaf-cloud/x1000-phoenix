def indicateurs(chevaux):
    actifs = [
        c for c in chevaux
        if c.get("non_partant") is False
    ]

    if len(actifs) < 5:
        return []

    profils = []
    for c in actifs:
        rangs = rangs_musique(c.get("musique"))

        if not rangs:
            return []

        points = [
            max(0, 11 - rang) / 10
            for rang in rangs
        ]

        forme = sum(points) / len(points)
        regularite = sum(
            rang <= 5 for rang in rangs
        ) / len(rangs)

        profils.append({
            "numero": c["numero"],
            "forme_recente": round(forme, 6),
            "regularite": round(regularite, 6),
            "gains_carriere": nombre(c.get("gains")),
            "observations": len(rangs)
        })

    gains = [
        p["gains_carriere"]
        for p in profils
        if p["gains_carriere"] is not None
    ]

    # Comparaison des gains uniquement
    # lorsque tous les chevaux sont renseignes.
    if len(gains) == len(profils) and max(gains) > 0:
        maximum = max(gains)
        for p in profils:
            p["gains_carriere"] = round(
                p["gains_carriere"] / maximum, 6
            )
    else:
        for p in profils:
            p["gains_carriere"] = None

    return profils
