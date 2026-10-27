// Réglages de départ de l'assistante.
// Alex : change ces valeurs avant d'offrir la clé. Ta mère peut aussi les
// modifier elle-même dans « Réglages » (ce qu'elle choisit là a priorité).
window.CONFIG_ASSISTANTE = {
  // Prénom de ta mère, pour le message d'accueil (« Bonjour Lise ! »).
  prenom: "",
  // Nom affiché de l'assistante, en haut de la fenêtre.
  nomAssistante: "Mon assistante",
  // Son travail, pour que l'assistante comprenne le contexte.
  entreprise: "Batteries Expert de Dolbeau-Mistassini",
  role: "secrétaire",
  contexte: "L'entreprise appartient à son mari.",
  // Signature ajoutée au bas des courriels et lettres (une ligne par élément).
  signature: "",

  // Moteur IA (ne pas changer sauf si tu sais pourquoi).
  temperature: 0.7,
  maxTokens: 1500,
  // Combien d'échanges récents on renvoie au modèle (la mémoire de la conversation).
  messagesGardes: 12,
};
