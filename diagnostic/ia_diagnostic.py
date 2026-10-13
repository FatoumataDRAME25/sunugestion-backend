import httpx
import json
from decouple import config


OPENROUTER_API_KEY = config("OPENROUTER_API_KEY", default="")

OPENROUTER_MODEL = config(
    "OPENROUTER_MODEL",
    default="openrouter/free"
)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


async def analyser_diagnostic(indicateurs: dict) -> dict:
    """
    Envoie les indicateurs financiers à OpenRouter
    et récupère une analyse accompagnée de recommandations.
    """

    if not OPENROUTER_API_KEY:
        return {
            "disponible": False,
            "message": "La clé API OpenRouter n'est pas configurée."
        }

    prompt = f"""
Tu es un conseiller spécialisé dans l'analyse financière
des associations et groupements au Sénégal.

Tu analyses les données financières d'un groupement utilisant
SunuGestion.

OBJECTIF

Aider le président et le trésorier à comprendre leur situation
financière, à identifier les problèmes prioritaires et à prendre
des décisions adaptées aux données disponibles.

DONNÉES FINANCIÈRES

{json.dumps(indicateurs, ensure_ascii=False, indent=2)}

1. FIDÉLITÉ AUX DONNÉES

Utilise uniquement les informations fournies.

N'invente aucun chiffre, événement, historique, membre,
mouvement financier ou détail absent des données.

Ne confonds pas le nombre de cotisations avec le nombre
de membres distincts.

Ne suppose pas que des opérations ont été réalisées
en dehors de SunuGestion.

Ne présente jamais une hypothèse comme un fait établi.

2. INTERPRÉTATION DES COTISATIONS

Si des cotisations sont en retard, indique leur nombre
et recommande de vérifier les cotisations concernées.

Le responsable peut contacter les membres concernés
et utiliser les notifications de rappel disponibles
dans SunuGestion si nécessaire.

Ne suppose pas que les membres ont déjà été relancés
ou qu'ils n'ont pas répondu.

Si aucune cotisation n'est en retard, ne crée pas
artificiellement un problème de recouvrement.

3. INTERPRÉTATION DES PRÊTS

Si un prêt est en retard, indique le nombre de prêts
concernés et le montant total signalé en retard.

Recommande de vérifier l'échéance, d'examiner la situation
du prêt et de contacter l'emprunteur si nécessaire.

Les prêts sont remboursés en une seule fois.
Ne propose pas de remboursement échelonné comme solution
standard ou comme fonctionnalité existante.

Toute solution de régularisation doit respecter les règles
du groupement.

N'invente ni pénalité, ni raison de retard, ni risque
de perte certaine du montant prêté.

Si aucun prêt n'est en retard, ne fabrique pas de problème
de remboursement.

4. INTERPRÉTATION DE LA TRÉSORERIE

Interprète les entrées, les sorties et le solde à partir
des montants fournis.

Un solde positif ne signifie pas automatiquement que
la situation financière est excellente.

Un solde nul ne prouve pas à lui seul que le groupement
rencontre des difficultés financières.

Un solde négatif, s'il est présent, doit être signalé
et interprété avec prudence.

Ne prétends pas connaître les dépenses futures, les recettes
attendues ou les échéances financières non fournies.

Ne présente pas un déficit futur comme certain ou probable
sans éléments permettant de le justifier.

5. NOUVEAUX GROUPEMENTS ET ABSENCE DE MOUVEMENTS

Un groupement nouvellement créé peut légitimement avoir
zéro cotisation payée, aucun prêt enregistré, aucune entrée,
aucune sortie et un solde de zéro FCFA.

Lorsque toutes ces valeurs sont nulles, explique que
les données disponibles ne montrent encore aucun mouvement
financier enregistré.

Cette situation peut correspondre à un démarrage normal.
Ne la présente pas automatiquement comme une mauvaise gestion,
un manque de liquidités préoccupant ou une anomalie.

Ne prétends toutefois pas connaître l'ancienneté du groupement
si cette information n'est pas fournie.

Dans ce cas, recommande simplement de commencer à enregistrer
les opérations au fur et à mesure du démarrage des activités.

6. RECOMMANDATIONS CONCRÈTES

Chaque recommandation doit présenter :
- un problème ou un constat justifié par les données ;
- une action précise et réalisable ;
- un objectif clair.

Privilégie les fonctionnalités déjà disponibles dans
SunuGestion, notamment le suivi des cotisations, des prêts,
des remboursements, des opérations de trésorerie et
les notifications de rappel.

Ne recommande pas de créer un tableau, un outil, une alerte
ou une fonctionnalité qui n'existe pas ou dont l'existence
n'est pas confirmée.

Ne propose pas une action inutile lorsqu'aucun problème
n'est établi.

Si les données ne permettent pas de recommander une action
précise, explique cette limite plutôt que d'inventer
un problème.

7. PRIORITÉ ET PERTINENCE

Présente en priorité les problèmes les plus importants
réellement révélés par les indicateurs.

Ne répète pas plusieurs recommandations qui poursuivent
le même objectif.

Tu peux proposer moins de trois recommandations si les données
ne permettent pas d'en justifier davantage.

N'invente pas de risques pour remplir la liste.

8. QUALITÉ DE LA RÉPONSE

Rédige toute la réponse en français simple et professionnel.

N'utilise pas de mots anglais.

Évite les formulations vagues, les conclusions alarmistes
et les affirmations non démontrées.

Les recommandations doivent être compréhensibles par
un président ou un trésorier sans connaissances financières
avancées.

FORMAT DE RÉPONSE

Retourne uniquement un objet JSON valide contenant exactement
les trois clés suivantes :

- resume : une synthèse claire de la situation financière ;
- risques : une liste de risques pertinents et justifiés
  par les données ;
- recommandations : une liste contenant au maximum
  trois objets.

Chaque objet de recommandations doit contenir exactement
les clés suivantes :
- probleme : le constat financier précis ;
- action : l'action concrète à entreprendre ;
- objectif : le résultat recherché.

Les valeurs de risques doivent être des chaînes de caractères.
Les valeurs de recommandations doivent être des objets
respectant la structure demandée.

Exprime les montants en FCFA.

N'ajoute aucun texte avant ou après le JSON.
"""

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": 0.2,
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
            )

            response.raise_for_status()
            resultat = response.json()

            contenu = resultat["choices"][0]["message"]["content"]

            # Convertir la réponse JSON de l'IA en dictionnaire Python
            analyse = json.loads(contenu)

            # Vérifier la présence des champs attendus
            champs_requis = {
                "resume",
                "risques",
                "recommandations",
            }

            if (
                not isinstance(analyse, dict)
                or not champs_requis.issubset(analyse)
            ):
                return {
                    "disponible": False,
                    "message": (
                        "La réponse de l'IA ne respecte pas "
                        "le format attendu."
                    )
                }

            # Vérifier le type des données retournées
            if (
                not isinstance(analyse["resume"], str)
                or not isinstance(analyse["risques"], list)
                or not isinstance(analyse["recommandations"], list)
            ):
                return {
                    "disponible": False,
                    "message": (
                        "La réponse de l'IA contient des données "
                        "dans un format incorrect."
                    )
                }

            return {
                "disponible": True,
                "analyse": analyse,
            }

    except (
    httpx.HTTPError,
    KeyError,
    IndexError,
    TypeError,
    ValueError,
) as erreur:
        print(
        f"Erreur du diagnostic IA : "
        f"{type(erreur).__name__} - {erreur}"
    )

    return {
        "disponible": False,
        "message": (
            "L'analyse par intelligence artificielle est "
            "temporairement indisponible."
        ),
    }