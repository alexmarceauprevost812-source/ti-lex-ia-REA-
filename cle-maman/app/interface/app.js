// Mon assistante — la fenêtre de discussion et de travail.
// Le moteur IA (llama.cpp) tourne sur cet ordinateur, à la même adresse que
// cette page : aucune donnée ne part sur internet.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const M = window.Markdown;
  const CFG = window.CONFIG_ASSISTANTE || {};

  // ------------------------------------------------------- petite mémoire
  const stock = {
    lire(cle, defaut) { try { const v = localStorage.getItem(cle); return v ? JSON.parse(v) : defaut; } catch { return defaut; } },
    ecrire(cle, val) {
      try { localStorage.setItem(cle, JSON.stringify(val)); return true; }
      catch { return false; }
    },
  };

  let reglages = Object.assign({ prenom: CFG.prenom || "", nomAssistante: CFG.nomAssistante || "Mon assistante", entreprise: CFG.entreprise || "", signature: CFG.signature || "", coordonnees: "", taille: 17, voixAuto: false, vitesseVoix: 1 }, stock.lire("reglages", {}));
  let conversations = stock.lire("conversations", []);
  let documents = stock.lire("documents", []);
  let courante = null;      // conversation affichée
  let joints = [];          // pièces jointes en attente { type:'image'|'texte', nom, data }
  let enCours = null;       // AbortController de la réponse en cours

  function sauver() {
    // Si la mémoire de la fenêtre est pleine, on retire les photos des plus
    // vieilles conversations (le texte, lui, est gardé).
    for (let essai = 0; essai < 30; essai++) {
      if (stock.ecrire("conversations", conversations)) return;
      const vieille = [...conversations].reverse().find((c) => c.messages.some((m) => m.images && m.images.length));
      if (!vieille) break;
      vieille.messages.forEach((m) => { if (m.images && m.images.length) { m.texte = (m.texte || "") + `\n[${m.images.length} photo(s) retirée(s) pour faire de la place]`; m.images = []; } });
    }
  }
  const sauverDocs = () => stock.ecrire("documents", documents.slice(0, 200));
  const id = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);

  // ---------------------------------------------------- consigne de l'IA
  function consigne() {
    const qui = reglages.prenom ? reglages.prenom : "la personne qui t'écrit";
    const lignes = [
      `Tu es ${reglages.nomAssistante || "l'assistante"}, l'assistante de bureau de ${qui}, ${CFG.role || "secrétaire"} chez ${reglages.entreprise || "une entreprise"} à Dolbeau-Mistassini, au Québec. ${CFG.contexte || ""}`,
      "Tu l'aides au travail (courriels aux clients et fournisseurs, lettres, avis, rappels de paiement, factures, listes, inventaires, horaires, affiches et publicités, résumés de notes, correction de textes) et dans la vie de tous les jours (recettes, questions pratiques, explications).",
      "",
      "Ta personnalité :",
      "- Tu es une vraie Québécoise du Lac-Saint-Jean : chaleureuse, souriante, terre à terre. Tu la tutoies et tu parles comme au Québec, avec des expressions d'ici quand ça adonne (« Pas de trouble ! », « Avec plaisir ! », « On s'y met ! », « C'est beau, c'est réglé ! »), sans en mettre partout.",
      "- Tu es toujours polie et bien élevée : JAMAIS de gros mots, de sacres ni de vulgarité, même pour rire, même si on t'en demande. Québécoise, oui ; vulgaire, jamais.",
      "- Tu AIMES travailler avec elle et ça paraît : tu es contente quand elle t'écrit et fière de ce que vous faites ensemble.",
      "- Tu l'encourages et tu soulignes sincèrement ses qualités et ses bons coups (son sens de l'organisation, sa patience avec les clients, une belle idée, un travail bien fait) — une phrase courte et vraie, pas de flatterie exagérée.",
      "- Tu fais du travail de qualité : soigné, sans fautes, bien présenté. Si tu vois une erreur ou un oubli dans sa demande (un montant qui ne balance pas, une date manquante), tu le lui dis gentiment.",
      "- Les textes pour les clients et fournisseurs restent en bon français professionnel, même si tu jases de façon familière avec elle.",
      "",
      "Façon de répondre :",
      "- Simple et clair, pas de jargon technique.",
      "- Va droit au but. Quand tu écris un texte à envoyer, donne directement le texte prêt à copier.",
      "- N'invente JAMAIS de prix, numéros de pièce, modèles compatibles, garanties, dates, adresses ou numéros de téléphone. S'il manque une info, mets un espace comme [prix] et dis-le.",
      "- Santé : donne de l'information générale et rappelle de consulter un pharmacien, un médecin ou Info-Santé 811 pour un cas personnel. Urgence : 911.",
      "- Tu fonctionnes sans internet : tu ne connais pas les nouvelles ni les prix du jour.",
      "",
      "Tes outils (utilise-les, ils sont exacts) :",
      "- calculer et taxes_quebec pour TOUS les calculs : ne calcule jamais de tête.",
      "- creer_document_word quand elle veut un document, une lettre ou un fichier à imprimer.",
      "- creer_tableau_excel pour une liste, un inventaire, une facture ou un tableau avec des totaux.",
      "- creer_affiche pour une publicité ou une promotion avec une photo, pour Facebook ou à imprimer.",
      "- dessiner_schema pour un plan, des étapes, un organigramme ou un planning.",
      "- creer_video pour une petite vidéo diaporama avec les photos.",
      "- creer_dossier et lister_documents pour classer ses fichiers.",
      "Après avoir utilisé un outil, dis en une phrase ce qui a été fait et où trouver le fichier.",
      "Les photos envoyées sont numérotées (photo 1, photo 2…) dans l'ordre de la conversation.",
    ];
    if (reglages.signature) lignes.push("", "Signature à mettre au bas des courriels et lettres :", reglages.signature);
    if (reglages.coordonnees) lignes.push("", "Coordonnées de l'entreprise (pour les affiches et lettres) :", reglages.coordonnees);
    return lignes.join("\n");
  }

  // ------------------------------------------------------------ raccourcis
  const RACCOURCIS = [
    ["✉️", "Courriel à un client", "Réponse polie, prête à envoyer", "Écris un courriel poli à un client pour lui dire que "],
    ["🧾", "Rappel de paiement", "Courtois mais clair", "Écris un rappel de paiement courtois pour la facture no [ ] de [montant], en retard depuis [date], pour le client "],
    ["✍️", "Corriger mon texte", "Fautes et tournures", "Corrige les fautes de ce texte sans changer le sens, et redonne-moi seulement le texte corrigé :\n\n"],
    ["📄", "Lettre en Word", "Un vrai fichier à imprimer", "Fais-moi un document Word : une lettre officielle de l'entreprise pour "],
    ["📊", "Tableau Excel", "Liste, inventaire, facture", "Fais-moi un tableau Excel avec les totaux pour "],
    ["🧮", "Calcul avec taxes", "TPS et TVQ exactes", "Calcule les taxes sur "],
    ["🖼️", "Affiche publicitaire", "Pour Facebook ou la vitrine", "Fais une affiche publicitaire pour donner envie aux clients d'acheter : "],
    ["🗺️", "Plan ou schéma", "Étapes, organigramme, planning", "Dessine-moi un schéma des étapes pour "],
    ["🎬", "Vidéo avec mes photos", "Petit diaporama en MP4", "Fais une petite vidéo avec mes photos pour "],
    ["📷", "Lire une photo", "Facture, étiquette, document", "@photo"],
    ["📝", "Résumer des notes", "En points clairs", "Fais un résumé clair, en points, de ces notes :\n\n"],
    ["🍲", "Idée de recette", "Avec ce que j'ai sous la main", "Propose-moi une recette simple pour ce soir avec "],
  ];

  function afficherRaccourcis() {
    $("raccourcis").innerHTML = "";
    for (const [emoji, titre, sous, modele] of RACCOURCIS) {
      const b = document.createElement("button");
      b.className = "raccourci";
      b.innerHTML = `<span class="emoji">${emoji}</span><div><strong>${M.echapper(titre)}</strong><span>${M.echapper(sous)}</span></div>`;
      b.onclick = () => {
        if (modele === "@photo") {
          $("message").value = "Qu'est-ce qu'on voit sur cette photo ? Si c'est un document, recopie-moi le texte.";
          $("fichier").click();
        } else {
          $("message").value = modele;
        }
        ajusterSaisie();
        $("message").focus();
        $("message").setSelectionRange($("message").value.length, $("message").value.length);
      };
      $("raccourcis").appendChild(b);
    }
  }

  // ------------------------------------------------------------ affichage
  function appliquerReglages() {
    document.documentElement.style.setProperty("--taille", reglages.taille + "px");
    $("nomAssistante").textContent = reglages.nomAssistante || "Mon assistante";
    document.title = reglages.nomAssistante || "Mon assistante";
    const h = new Date().getHours();
    const bonjour = h < 5 || h >= 18 ? "Bonsoir" : "Bonjour";
    $("salutation").textContent = reglages.prenom ? `${bonjour} ${reglages.prenom} !` : `${bonjour} !`;
  }

  function quand(t) {
    const d = new Date(t), auj = new Date();
    if (d.toDateString() === auj.toDateString()) return d.toLocaleTimeString("fr-CA", { hour: "2-digit", minute: "2-digit" });
    return d.toLocaleDateString("fr-CA", { day: "numeric", month: "short" });
  }

  function afficherListe() {
    const l = $("listeConversations");
    l.innerHTML = "";
    if (!conversations.length) { l.innerHTML = `<div class="vide">Tes conversations apparaîtront ici.</div>`; }
    for (const c of conversations) {
      const e = document.createElement("div");
      e.className = "element" + (courante && c.id === courante.id ? " actif" : "");
      e.tabIndex = 0;
      e.innerHTML = `<span class="element-texte">${M.echapper(c.titre)}<span class="element-sous">${quand(c.maj)}</span></span><button class="suppr" title="Supprimer" aria-label="Supprimer">🗑️</button>`;
      e.onclick = (ev) => { if (!ev.target.closest(".suppr")) ouvrir(c.id); };
      e.onkeydown = (ev) => { if (ev.key === "Enter") ouvrir(c.id); };
      e.querySelector(".suppr").onclick = () => {
        if (!confirm(`Supprimer la conversation « ${c.titre} » ?`)) return;
        conversations = conversations.filter((x) => x.id !== c.id);
        sauver();
        if (courante && courante.id === c.id) nouvelle(); else afficherListe();
      };
      l.appendChild(e);
    }
    const d = $("listeDocuments");
    d.innerHTML = documents.length ? "" : `<div class="vide">Les documents, tableaux, affiches et vidéos créés apparaîtront ici. Ils sont dans le dossier « Mes documents » de la clé.</div>`;
    for (const doc of documents) {
      const e = document.createElement("div");
      e.className = "element";
      e.innerHTML = `<span>${doc.icone || "📄"}</span><span class="element-texte">${M.echapper(doc.nom)}<span class="element-sous">${M.echapper(doc.ou)} · ${quand(doc.date)}</span></span>`;
      e.title = `Dans : ${doc.ou}`;
      d.appendChild(e);
    }
  }

  function bulleElle(msg) {
    const box = document.createElement("div");
    box.className = "msg elle";
    const cartes = document.createElement("div");
    cartes.className = "cartes";
    cartes.style.cssText = "display:flex;flex-direction:column;gap:8px";
    const b = document.createElement("div");
    b.className = "bulle";
    const actions = document.createElement("div");
    actions.className = "actions-msg";
    box.append(cartes, b, actions);
    (msg.cartes || []).forEach((c) => cartes.appendChild(carte(c)));
    if (msg.texte) b.innerHTML = M.html(msg.texte); else b.classList.add("cache");
    if (msg.texte) ajouterActions(actions, msg);
    return { box, bulle: b, cartes, actions };
  }

  function afficherMessage(msg) {
    if (msg.role === "user") {
      const box = document.createElement("div");
      box.className = "msg moi";
      if (msg.images && msg.images.length) {
        const p = document.createElement("div");
        p.className = "photos";
        msg.images.forEach((src) => { const i = new Image(); i.src = src; i.alt = "photo"; p.appendChild(i); });
        box.appendChild(p);
      }
      if (msg.fichiers && msg.fichiers.length) {
        const j = document.createElement("div");
        j.className = "joint";
        j.textContent = "📎 " + msg.fichiers.join(", ");
        box.appendChild(j);
      }
      if (msg.affiche) { const b = document.createElement("div"); b.className = "bulle"; b.textContent = msg.affiche; box.appendChild(b); }
      $("fil").appendChild(box);
      return box;
    }
    const r = bulleElle(msg);
    $("fil").appendChild(r.box);
    return r;
  }

  function afficherConversation() {
    const fil = $("fil");
    [...fil.children].forEach((n) => { if (n.id !== "accueil") n.remove(); });
    const vide = !courante || !courante.messages.length;
    $("accueil").classList.toggle("cache", !vide);
    $("titreConversation").textContent = vide ? "Nouvelle conversation" : courante.titre;
    if (!vide) courante.messages.forEach(afficherMessage);
    defiler(true);
  }

  function defiler(force) {
    const f = $("fil");
    if (force || f.scrollHeight - f.scrollTop - f.clientHeight < 160) f.scrollTop = f.scrollHeight;
  }

  // ------------------------------------------------------ cartes d'outils
  function carte(c) {
    const box = document.createElement("div");
    if (c.genre === "calcul" || c.genre === "erreur") {
      box.className = "carte " + c.genre;
      box.innerHTML = `<span class="gros">${c.genre === "erreur" ? "⚠️" : "🧮"}</span><div class="infos"><strong>${M.echapper(c.titre)}</strong><span>${M.echapper(c.detail)}</span></div>`;
      return box;
    }
    box.className = "carte";
    box.style.flexWrap = "wrap";
    const ou = c.mode === "dossier" ? `Enregistré dans ${c.ou}` : `Enregistré dans ${c.ou} (sur la clé)`;
    box.innerHTML = `<span class="gros">${c.icone || "📄"}</span><div class="infos"><strong>${M.echapper(c.nom)}</strong><span>${M.echapper(ou)}</span></div>`;
    if (c.blob) {
      const b = document.createElement("button");
      b.className = "bouton petit";
      b.textContent = "Ouvrir";
      b.title = "Ouvre le fichier (dans Word, Excel ou le lecteur d'images)";
      b.onclick = () => Outils.telecharger(c.blob, c.nom);
      box.appendChild(b);
    }
    if (c.svg || c.url || (c.genre === "video" && c.blob)) {
      const v = document.createElement("div");
      v.className = "carte-visuel";
      v.style.flexBasis = "100%";
      if (c.svg) v.innerHTML = c.svg;  // produit par Mermaid en mode strict
      else if (c.url) { const i = new Image(); i.src = c.url; i.alt = c.nom; v.appendChild(i); }
      else { const vid = document.createElement("video"); vid.controls = true; vid.src = URL.createObjectURL(c.blob); vid.style.maxWidth = "100%"; v.appendChild(vid); }
      box.appendChild(v);
    }
    return box;
  }

  function noterDocument(c) {
    documents.unshift({ nom: c.nom, ou: c.ou, icone: c.icone, date: Date.now() });
    sauverDocs();
    afficherListe();
  }

  // ----------------------------------------------------------------- voix
  // Lecture à voix haute avec les voix de Windows installées sur l'ordinateur
  // (localService) : le texte n'est pas envoyé sur internet. On préfère une
  // voix du Québec (fr-CA), sinon une autre voix française.
  const voix = {
    choisie: null,
    bouton: null,
    choisir() {
      const toutes = speechSynthesis.getVoices();
      const locales = toutes.filter((v) => v.localService);
      this.choisie = locales.find((v) => /^fr-CA/i.test(v.lang)) || locales.find((v) => /^fr/i.test(v.lang)) || null;
      return this.choisie;
    },
    arreter() {
      speechSynthesis.cancel();
      if (this.bouton) this.bouton.textContent = "🔊 Écouter";
      this.bouton = null;
    },
    lire(texte, bouton) {
      if (!("speechSynthesis" in window)) return;
      const etaitCeluiLa = this.bouton === bouton;
      this.arreter();
      if (etaitCeluiLa) return;
      if (!this.choisie && !this.choisir()) {
        bandeau("Aucune voix française n'est installée sur cet ordinateur. Dans Windows : Paramètres › Heure et langue › Voix › Ajouter des voix › Français (Canada).");
        return;
      }
      // Par phrases : les longues lectures d'un seul bloc peuvent couper.
      const phrases = M.texteSimple(texte).replace(/[•*#|]/g, " ").match(/[^.!?\n]+[.!?]*\s*/g) || [];
      if (!phrases.length) return;
      this.bouton = bouton || null;
      if (bouton) bouton.textContent = "⏹ Arrêter";
      phrases.forEach((p, i) => {
        const u = new SpeechSynthesisUtterance(p.trim());
        u.voice = this.choisie; u.lang = this.choisie.lang; u.rate = reglages.vitesseVoix || 1;
        if (i === phrases.length - 1) u.onend = () => { if (this.bouton === bouton) { if (bouton) bouton.textContent = "🔊 Écouter"; this.bouton = null; } };
        speechSynthesis.speak(u);
      });
    },
  };
  if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = () => voix.choisir();

  // Boutons sous chaque réponse : Copier, Écouter, Word, Excel, Recommencer.
  function ajouterActions(zone, msg) {
    zone.innerHTML = "";
    const bouton = (texte, titre, action) => {
      const b = document.createElement("button");
      b.className = "bouton fantome";
      b.textContent = texte; b.title = titre;
      b.onclick = action;
      zone.appendChild(b);
      return b;
    };
    const copier = bouton("📋 Copier", "Copier le texte pour le coller ailleurs", async () => {
      try { await navigator.clipboard.writeText(M.texteSimple(msg.texte)); copier.textContent = "✔ Copié"; }
      catch { copier.textContent = "Copie impossible"; }
      setTimeout(() => (copier.textContent = "📋 Copier"), 1800);
    });
    if ("speechSynthesis" in window) {
      const ecouter = bouton("🔊 Écouter", "Lire la réponse à voix haute", () => voix.lire(msg.texte, ecouter));
      zone._ecouter = ecouter;
    }
    bouton("📄 Mettre dans Word", "Créer un fichier Word avec cette réponse", async () => {
      const titre = (M.blocs(msg.texte).find((b) => b.type === "h") || {}).text || "";
      const nom = prompt("Nom du document :", (titre || (courante && courante.titre) || "Document").slice(0, 60));
      if (!nom) return;
      const blob = await Outils.docxDepuisMarkdown("", msg.texte);
      const f = await Outils.enregistrer(blob, Outils.nomPropre(nom, "docx"));
      noterDocument({ ...f, icone: "📄" });
      zone.parentElement.querySelector(".cartes").appendChild(carte({ genre: "fichier", icone: "📄", ...f }));
    });
    const tableau = M.blocs(msg.texte).find((b) => b.type === "table");
    if (tableau) {
      bouton("📊 Mettre dans Excel", "Créer un fichier Excel avec ce tableau", async () => {
        const nom = prompt("Nom du tableau :", (courante && courante.titre ? courante.titre : "Tableau").slice(0, 60));
        if (!nom) return;
        const [tete, ...corps] = tableau.rows;
        const plat = (t) => M.morceaux(t).map((m) => m.text).join("");
        const nums = tete.map((_, c) => corps.length && corps.every((r) => Outils.lireNombre(plat(r[c] || "")) !== null));
        const totaliser = tete.filter((_, c) => nums[c] && !/(no|num|#|code|année|an|qté unitaire)/i.test(plat(tete[c]))).map(plat);
        const blob = Outils.xlsxDepuisTableau(nom, tete.map(plat), corps.map((r) => r.map(plat)), totaliser);
        const f = await Outils.enregistrer(blob, Outils.nomPropre(nom, "xlsx"));
        noterDocument({ ...f, icone: "📊" });
        zone.parentElement.querySelector(".cartes").appendChild(carte({ genre: "fichier", icone: "📊", ...f }));
      });
    }
    if (courante && courante.messages[courante.messages.length - 1] === msg) {
      const refaire = bouton("🔁 Recommencer", "Écrire une autre réponse", () => {
        // Seulement si cette réponse est encore la dernière de la conversation.
        if (enCours || !courante || courante.messages[courante.messages.length - 1] !== msg) return;
        courante.messages.pop();
        sauver();
        afficherConversation();
        repondre();
      });
      refaire.classList.add("recommencer");
    }
  }

  // ------------------------------------------------------ pièces jointes
  function redimensionner(fichier, max = 1024) {
    return new Promise((ok, ko) => {
      const lecteur = new FileReader();
      lecteur.onload = () => {
        const img = new Image();
        img.onload = () => {
          const r = Math.min(1, max / Math.max(img.width, img.height));
          const c = document.createElement("canvas");
          c.width = Math.round(img.width * r); c.height = Math.round(img.height * r);
          c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
          ok(c.toDataURL("image/jpeg", 0.85));
        };
        img.onerror = () => ko(new Error("Image illisible"));
        img.src = lecteur.result;
      };
      lecteur.onerror = () => ko(lecteur.error);
      lecteur.readAsDataURL(fichier);
    });
  }

  async function lireFichier(f) {
    const nom = f.name || "fichier";
    const ext = nom.split(".").pop().toLowerCase();
    if (f.type.startsWith("image/")) return { type: "image", nom, data: await redimensionner(f) };
    if (ext === "docx") {
      const r = await mammoth.extractRawText({ arrayBuffer: await f.arrayBuffer() });
      return { type: "texte", nom, data: r.value };
    }
    if (ext === "xlsx" || ext === "xls") {
      const wb = XLSX.read(await f.arrayBuffer(), { type: "array" });
      return { type: "texte", nom, data: wb.SheetNames.map((s) => `--- Feuille « ${s} » ---\n` + XLSX.utils.sheet_to_csv(wb.Sheets[s], { FS: " | " })).join("\n\n") };
    }
    if (["txt", "csv", "md"].includes(ext) || f.type.startsWith("text/")) return { type: "texte", nom, data: await f.text() };
    throw new Error(`Je ne sais pas encore lire les fichiers « .${ext} ». Essaie une photo, un Word, un Excel ou un texte.`);
  }

  async function ajouterFichiers(liste) {
    for (const f of liste) {
      try { joints.push(await lireFichier(f)); }
      catch (e) { bandeau(e.message); }
    }
    afficherJoints();
  }

  function afficherJoints() {
    const z = $("apercus");
    z.innerHTML = "";
    joints.forEach((j, k) => {
      const a = document.createElement("div");
      a.className = "apercu";
      a.innerHTML = j.type === "image" ? `<img src="${j.data}" alt="">` : `<span>📄 ${M.echapper(j.nom)}</span>`;
      const x = document.createElement("button");
      x.textContent = "×"; x.title = "Retirer"; x.setAttribute("aria-label", "Retirer");
      x.onclick = () => { joints.splice(k, 1); afficherJoints(); };
      a.appendChild(x);
      z.appendChild(a);
    });
  }

  // --------------------------------------------------------- conversation
  function nouvelle() {
    courante = null;
    afficherConversation();
    afficherListe();
    $("message").focus();
  }

  function ouvrir(cid) {
    courante = conversations.find((c) => c.id === cid) || null;
    afficherConversation();
    afficherListe();
    $("cote").classList.remove("ouvert");
  }

  // Toutes les photos de la conversation, dans l'ordre (photo 1, photo 2…).
  const photosDe = (conv) => (conv ? conv.messages.flatMap((m) => m.images || []) : []);

  async function envoyer() {
    const texte = $("message").value.trim();
    if ((!texte && !joints.length) || enCours) return;
    voix.arreter();
    document.querySelectorAll(".recommencer").forEach((b) => b.remove());
    if (!courante) {
      courante = { id: id(), titre: (texte || "Photo").replace(/\s+/g, " ").slice(0, 48), messages: [], maj: Date.now() };
      conversations.unshift(courante);
    }
    const avant = photosDe(courante).length;
    const images = joints.filter((j) => j.type === "image").map((j) => j.data);
    const textes = joints.filter((j) => j.type === "texte");
    let contenu = texte;
    if (images.length) contenu = `(Photo${images.length > 1 ? "s" : ""} jointe${images.length > 1 ? "s" : ""} : ${images.map((_, k) => "photo " + (avant + k + 1)).join(", ")})\n` + contenu;
    for (const t of textes) contenu += `\n\n--- Contenu du fichier « ${t.nom} » ---\n${t.data.slice(0, 20000)}`;
    const msg = { role: "user", texte: contenu, affiche: texte, images, fichiers: joints.map((j) => j.nom).filter((n, k) => joints[k].type === "texte" || !n.startsWith("image")) };
    courante.messages.push(msg);
    courante.maj = Date.now();
    conversations = [courante, ...conversations.filter((c) => c.id !== courante.id)];
    joints = [];
    afficherJoints();
    $("message").value = "";
    ajusterSaisie();
    $("accueil").classList.add("cache");
    $("titreConversation").textContent = courante.titre;
    afficherMessage(msg);
    defiler(true);
    sauver();
    afficherListe();
    await repondre();
  }

  // Messages envoyés au moteur : consigne + derniers échanges. Les photos ne
  // sont renvoyées que pour les 4 derniers messages (plus rapide).
  function pourLeModele() {
    const garde = courante.messages.slice(-(CFG.messagesGardes || 12));
    const n = garde.length;
    let compteur = photosDe(courante).length - garde.reduce((s, m) => s + (m.images || []).length, 0);
    const out = [{ role: "system", content: consigne() }];
    garde.forEach((m, k) => {
      if (m.role === "user") {
        const imgs = m.images || [];
        if (imgs.length && k >= n - 4) {
          out.push({ role: "user", content: [{ type: "text", text: m.texte || "Voici la photo." }, ...imgs.map((src) => ({ type: "image_url", image_url: { url: src } }))] });
        } else {
          out.push({ role: "user", content: m.texte + (imgs.length ? `\n[${imgs.length} photo(s) envoyée(s) plus tôt]` : "") });
        }
        compteur += imgs.length;
      } else {
        const fichiers = (m.cartes || []).filter((c) => c.nom).map((c) => `[Fichier créé : ${c.nom}]`).join("\n");
        out.push({ role: "assistant", content: [fichiers, m.texte].filter(Boolean).join("\n") || "(fait)" });
      }
    });
    return out;
  }

  // Lit la réponse du moteur au fur et à mesure (texte + appels d'outils).
  async function demander(messages, signal, surTexte) {
    const r = await fetch("/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal,
      body: JSON.stringify({
        messages, stream: true, tools: Outils.SCHEMAS,
        temperature: CFG.temperature ?? 0.7, top_p: 0.8, top_k: 20, repeat_penalty: 1.05,
        max_tokens: CFG.maxTokens || 1500,
      }),
    });
    if (!r.ok) {
      let detail = "";
      try { detail = (await r.json()).error?.message || ""; } catch {}
      throw new Error(r.status === 503 ? "L'assistante finit de se réveiller, réessaie dans quelques secondes." : `Le moteur a répondu une erreur (${r.status}). ${detail}`);
    }
    const lecteur = r.body.getReader();
    const dec = new TextDecoder();
    let tampon = "", texte = "";
    const appels = [];
    for (;;) {
      const { value, done } = await lecteur.read();
      if (done) break;
      tampon += dec.decode(value, { stream: true });
      const lignes = tampon.split("\n");
      tampon = lignes.pop();
      for (const l of lignes) {
        const t = l.trim();
        if (!t.startsWith("data:")) continue;
        const data = t.slice(5).trim();
        if (data === "[DONE]") continue;
        let j;
        try { j = JSON.parse(data); } catch { continue; }
        const d = j.choices && j.choices[0] && j.choices[0].delta;
        if (!d) continue;
        if (d.content) { texte += d.content; surTexte(texte); }
        for (const tc of d.tool_calls || []) {
          const k = tc.index ?? appels.length;
          appels[k] = appels[k] || { id: tc.id || "appel" + k, type: "function", function: { name: "", arguments: "" } };
          if (tc.id) appels[k].id = tc.id;
          if (tc.function?.name) appels[k].function.name += tc.function.name;
          if (tc.function?.arguments) appels[k].function.arguments += tc.function.arguments;
        }
      }
    }
    return { texte, appels: appels.filter(Boolean) };
  }

  async function repondre() {
    const conv = courante;
    const msg = { role: "assistant", texte: "", cartes: [] };
    const vue = bulleElle(msg);
    vue.bulle.classList.remove("cache");
    vue.bulle.innerHTML = `<span class="ecrit curseur">Je réfléchis</span>`;
    $("fil").appendChild(vue.box);
    defiler(true);
    enCours = new AbortController();
    $("envoyer").classList.add("cache");
    $("arreter").classList.remove("cache");

    const messages = pourLeModele();
    let texteFinal = "";
    try {
      for (let tour = 0; tour < 6; tour++) {
        const { texte, appels } = await demander(messages, enCours.signal, (t) => {
          vue.bulle.innerHTML = M.html(t);
          vue.bulle.lastElementChild && vue.bulle.lastElementChild.classList.add("curseur");
          defiler();
        });
        texteFinal = texte;
        if (!appels.length) break;
        messages.push({ role: "assistant", content: texte || "", tool_calls: appels });
        for (const a of appels) {
          let args = {};
          try { args = a.function.arguments ? JSON.parse(a.function.arguments) : {}; } catch { args = null; }
          const attente = document.createElement("div");
          attente.className = "carte";
          attente.innerHTML = `<span class="gros">⏳</span><div class="infos"><strong>Je m'en occupe…</strong><span>${M.echapper(nomOutil(a.function.name))}</span><div class="progres"><div></div></div></div>`;
          vue.cartes.appendChild(attente);
          defiler();
          let resultat;
          try {
            if (args === null) throw new Error("Les informations reçues étaient mal formées.");
            const r = await Outils.executer(a.function.name, args, {
              photos: photosDe(conv),
              coordonnees: reglages.coordonnees,
              progres: (p) => { const b = attente.querySelector(".progres > div"); if (b) b.style.width = Math.round(p * 100) + "%"; },
            });
            resultat = r.texte;
            attente.remove();
            if (r.carte) {
              msg.cartes.push(r.carte);
              vue.cartes.appendChild(carte(r.carte));
              if (r.carte.nom) noterDocument(r.carte);
            }
          } catch (e) {
            resultat = "Erreur : " + (e.message || e);
            attente.remove();
            const c = { genre: "erreur", titre: "Ça n'a pas marché", detail: e.message || String(e) };
            msg.cartes.push(c);
            vue.cartes.appendChild(carte(c));
          }
          messages.push({ role: "tool", tool_call_id: a.id, name: a.function.name, content: resultat });
          defiler();
        }
        vue.bulle.innerHTML = `<span class="ecrit curseur">Je termine</span>`;
      }
    } catch (e) {
      if (e.name === "AbortError") texteFinal = (texteFinal || "") + "\n\n*(Arrêté.)*";
      else {
        texteFinal = "Oups, je n'arrive pas à répondre : " + (e.message || e) + "\n\nSi ça continue, ferme la fenêtre et redémarre l'assistante.";
        verifierMoteur();
      }
    }
    enCours = null;
    $("envoyer").classList.remove("cache");
    $("arreter").classList.add("cache");
    msg.texte = texteFinal.trim();
    if (!msg.texte && !msg.cartes.length) msg.texte = "(Je n'ai rien trouvé à répondre. Peux-tu reformuler ?)";
    // Les fichiers (blob) ne sont pas gardés en mémoire permanente : ils sont sur la clé.
    const aGarder = { ...msg, cartes: msg.cartes.map(({ blob, url, ...reste }) => reste) };
    conv.messages.push(aGarder);
    conv.maj = Date.now();
    sauver();
    if (msg.texte) { vue.bulle.classList.remove("cache"); vue.bulle.innerHTML = M.html(msg.texte); } else vue.bulle.classList.add("cache");
    // Les boutons utilisent la version affichée (avec le fichier pour « Ouvrir »).
    if (msg.texte) {
      ajouterActions(vue.actions, aGarder);
      if (reglages.voixAuto && vue.actions._ecouter) voix.lire(aGarder.texte, vue.actions._ecouter);
    }
    if (courante === conv) afficherListe();
    defiler();
  }

  const nomOutil = (n) => ({
    calculer: "Calcul", taxes_quebec: "Calcul des taxes", creer_document_word: "Création du document Word",
    creer_tableau_excel: "Création du tableau Excel", creer_affiche: "Création de l'affiche", dessiner_schema: "Dessin du schéma",
    creer_video: "Fabrication de la vidéo (ça prend le temps de la vidéo)", creer_dossier: "Création du dossier", lister_documents: "Liste des documents",
  }[n] || n);

  // -------------------------------------------------------------- divers
  function bandeau(texte, bouton) {
    const b = $("bandeau");
    b.innerHTML = `<span style="flex:1">${M.echapper(texte)}</span>`;
    if (bouton) { const x = document.createElement("button"); x.className = "bouton petit"; x.textContent = bouton.texte; x.onclick = bouton.action; b.appendChild(x); }
    const f = document.createElement("button"); f.className = "bouton fantome petit"; f.textContent = "×"; f.setAttribute("aria-label", "Fermer"); f.onclick = () => b.classList.add("cache");
    b.appendChild(f);
    b.classList.remove("cache");
  }

  async function verifierMoteur() {
    try {
      const r = await fetch("/health", { cache: "no-store" });
      if (r.ok) { $("bandeau").classList.add("cache"); return true; }
      bandeau("L'assistante finit de se réveiller… encore quelques secondes.");
    } catch {
      bandeau("L'assistante ne répond plus. Ferme cette fenêtre et double-clique de nouveau sur « Démarrer l'assistante ».");
    }
    setTimeout(verifierMoteur, 4000);
    return false;
  }

  async function afficherDossier() {
    const e = Outils.etatDossier();
    const z = $("dossierEtat");
    z.innerHTML = "";
    if (!e.nom) { z.textContent = "📁 Fichiers : dossier « Mes documents » de la clé"; $("rDossier").textContent = "Par défaut : « Mes documents » sur la clé."; return; }
    $("rDossier").textContent = `« ${e.nom} »` + (e.pret ? "" : " — à reconnecter");
    if (e.pret) { z.textContent = `📁 Dossier de travail : ${e.nom}`; return; }
    z.textContent = `📁 « ${e.nom} » doit être reconnecté.`;
    const b = document.createElement("button");
    b.className = "bouton petit plein"; b.textContent = "Reconnecter mon dossier";
    b.onclick = async () => { try { await Outils.reconnecterDossier(); } catch {} afficherDossier(); };
    z.appendChild(b);
  }

  function ajusterSaisie() {
    const t = $("message");
    t.style.height = "auto";
    t.style.height = Math.min(240, t.scrollHeight) + "px";
  }

  // ------------------------------------------------------------ branchements
  $("envoyer").onclick = envoyer;
  $("arreter").onclick = () => enCours && enCours.abort();
  $("nouvelle").onclick = nouvelle;
  $("menu").onclick = () => $("cote").classList.toggle("ouvert");
  $("message").addEventListener("input", ajusterSaisie);
  $("message").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); envoyer(); }
  });
  $("joindre").onclick = () => $("fichier").click();
  $("fichier").onchange = (e) => { ajouterFichiers([...e.target.files]); e.target.value = ""; };
  document.addEventListener("paste", (e) => {
    const f = [...(e.clipboardData?.files || [])];
    if (f.length) { e.preventDefault(); ajouterFichiers(f); }
  });
  const zone = document.querySelector(".principal-zone");
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("depot"); });
  zone.addEventListener("dragleave", (e) => { if (!zone.contains(e.relatedTarget)) zone.classList.remove("depot"); });
  zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("depot"); ajouterFichiers([...e.dataTransfer.files]); });

  document.querySelectorAll(".onglet").forEach((o) => (o.onclick = () => {
    document.querySelectorAll(".onglet").forEach((x) => x.classList.toggle("actif", x === o));
    $("listeConversations").classList.toggle("cache", o.dataset.onglet !== "conversations");
    $("listeDocuments").classList.toggle("cache", o.dataset.onglet !== "documents");
  }));

  $("textePlus").onclick = () => { reglages.taille = Math.min(26, reglages.taille + 1); stock.ecrire("reglages", reglages); appliquerReglages(); };
  $("texteMoins").onclick = () => { reglages.taille = Math.max(13, reglages.taille - 1); stock.ecrire("reglages", reglages); appliquerReglages(); };

  $("ouvrirReglages").onclick = () => {
    $("rPrenom").value = reglages.prenom; $("rNom").value = reglages.nomAssistante; $("rEntreprise").value = reglages.entreprise;
    $("rSignature").value = reglages.signature; $("rCoordonnees").value = reglages.coordonnees;
    $("rVoixAuto").checked = !!reglages.voixAuto; $("rVitesse").value = reglages.vitesseVoix || 1;
    afficherDossier();
    $("reglages").showModal();
  };
  $("rChoisir").onclick = async () => {
    try { await Outils.choisirDossier(); } catch (e) { if (e.name !== "AbortError") alert(e.message); }
    afficherDossier();
  };
  $("reglages").addEventListener("close", () => {
    if ($("reglages").returnValue !== "ok") return;
    reglages.prenom = $("rPrenom").value.trim();
    reglages.nomAssistante = $("rNom").value.trim() || "Mon assistante";
    reglages.entreprise = $("rEntreprise").value.trim();
    reglages.signature = $("rSignature").value.trim();
    reglages.coordonnees = $("rCoordonnees").value.trim();
    reglages.voixAuto = $("rVoixAuto").checked;
    reglages.vitesseVoix = parseFloat($("rVitesse").value) || 1;
    stock.ecrire("reglages", reglages);
    appliquerReglages();
  });

  // ---------------------------------------------------------------- départ
  appliquerReglages();
  afficherRaccourcis();
  afficherListe();
  afficherConversation();
  Outils.chargerDossier().then(afficherDossier);
  verifierMoteur();
  $("message").focus();
})();
