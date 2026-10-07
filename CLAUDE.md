# Agent-cv

Agent d'adaptation de CV aux appels d'offres, déployé sur Railway depuis `main` (auto-deploy).

## Sessions cloud (claude.ai/code, téléphone) : rester sur sa branche

`main` déclenche le déploiement en production. En session cloud, le travail
reste donc sur sa branche `claude/...`, poussée sur GitHub, et **ne passe
jamais sur `main` depuis le cloud**. Terminer la réponse en nommant la branche
et ce qu'elle contient. Au démarrage de session sur le Mac, toute branche
`claude/*` absente de `main` est signalée, et Diane décide de la fusion
(vérifications locales comprises).
