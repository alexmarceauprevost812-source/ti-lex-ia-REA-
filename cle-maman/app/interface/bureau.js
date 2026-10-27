// Le « mini PC » de la clé : un bureau avec de grosses icônes, une barre des
// tâches comme Windows, et de petites applis (Mes documents, Calculatrice,
// Bloc-notes, Créateur d'affiches) à côté de l'assistante.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const M = window.Markdown;
  const A = window.Assistante;

  const APPLIS = [
    { vue: "assistante", icone: "💬", nom: "Assistante", sous: "Jaser et travailler avec l'IA", couleur: "#0067c0" },
    { vue: "documents", icone: "📁", nom: "Mes documents", sous: "Tes fichiers sur la clé", couleur: "#c47f00" },
    { vue: "calcul", icone: "🧮", nom: "Calculatrice", sous: "Avec TPS et TVQ", couleur: "#0f7b0f" },
    { vue: "notes", icone: "📝", nom: "Bloc-notes", sous: "Notes et brouillons", couleur: "#6b3fa0" },
    { vue: "affiche", icone: "🖼️", nom: "Affiches", sous: "Publicités pour le magasin", couleur: "#b3121b" },
    { vue: "guide", icone: "📖", nom: "Guide", sous: "Comment ça marche", couleur: "#00838f" },
    { vue: "corbeille", image: "img/corbeille.png", icone: "🗑️", nom: "Corbeille", sous: "Fichiers supprimés", couleur: "#4a6a8a" },
    { vue: "reglages", image: "img/reglages.png", icone: "⚙️", nom: "Réglages", sous: "Thème, couleurs, voix", couleur: "#5f5f5f" },
  ];

  // ----------------------------------------------------------- navigation
  let vueActive = "bureau";
  function ouvrir(vue) {
    if (vue === "reglages") { $("ouvrirReglages").click(); return; }
    vueActive = vue;
    const ecran = vue === "corbeille" ? "documents" : vue;
    if (vue === "corbeille" || vue === "documents") { docs.mode = vue; docs.chemin = []; }
    document.querySelectorAll(".vue").forEach((v) => v.classList.toggle("cache", v.id !== "vue-" + ecran));
    document.querySelectorAll(".tache").forEach((t) => t.classList.toggle("actif", t.dataset.vue === vue));
    if (vue === "bureau") afficherBureau();
    if (ecran === "documents") docs.afficher();
    if (vue === "notes") notes.afficher();
    if (vue === "calcul") setTimeout(() => $("calcEcran").focus(), 30);
    if (vue === "alex") alex.afficher();
    $("boutonAlex").classList.toggle("actif", vue === "alex");
    if (vue === "assistante") setTimeout(() => $("message").focus(), 30);
  }
  window.ouvrirAppli = ouvrir;

  function barreTaches() {
    const t = $("taches");
    t.querySelectorAll(".tache:not(.demarrer)").forEach((x) => x.remove());
    for (const a of APPLIS.filter((x) => x.vue !== "reglages" && x.vue !== "corbeille")) {
      const b = document.createElement("button");
      b.className = "tache"; b.dataset.vue = a.vue; b.title = a.nom; b.setAttribute("aria-label", a.nom);
      b.innerHTML = a.image ? `<img src="${a.image}" alt="">` : `<span>${a.icone}</span>`;
      b.onclick = () => ouvrir(a.vue);
      t.appendChild(b);
    }
    $("boutonDemarrer").onclick = (e) => { e.stopPropagation(); menu.basculer(); };
  }

  function horloge() {
    const d = new Date();
    $("horloge").innerHTML = `<div>${d.toLocaleTimeString("fr-CA", { hour: "2-digit", minute: "2-digit" })}</div><div>${d.toLocaleDateString("fr-CA")}</div>`;
  }

  // --------------------------------------------------------------- bureau
  function afficherBureau() {
    const r = A.reglages();
    const h = new Date().getHours();
    const question = h >= 18 || h < 5 ? "On termine quelque chose ensemble ?" : "Prête à travailler ?";
    A.ecrireDoucement($("bureauSalut"), (r.prenom ? `Salut ${r.prenom} ! ` : "Salut ! ") + question);
    const date = new Date().toLocaleDateString("fr-CA", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    $("bureauDate").textContent = date.charAt(0).toUpperCase() + date.slice(1);
    const rec = $("bureauRecents");
    const liste = (A.documents() || []).slice(0, 6);
    rec.innerHTML = liste.length ? "" : `<span class="petit">Rien encore — demande à l'assistante une lettre, un tableau ou une affiche !</span>`;
    for (const d of liste) {
      const e = document.createElement("div");
      e.className = "recent";
      e.innerHTML = `<span>${d.icone || "📄"}</span><span class="recent-nom">${M.echapper(d.nom)}</span>`;
      e.title = "Dans : " + d.ou;
      rec.appendChild(e);
    }
  }

  // Icônes du bureau, comme sur un PC : image + nom, en colonnes à gauche.
  // Un seul clic suffit pour ouvrir (plus simple que le double-clic).
  function tuiles() {
    const t = $("tuiles");
    t.innerHTML = "";
    for (const a of APPLIS) {
      const b = document.createElement("button");
      b.className = "icone-bureau";
      b.setAttribute("role", "listitem");
      b.title = a.sous;
      b.style.setProperty("--c", a.couleur);
      const ic = a.image ? `<img src="${a.image}" alt="">` : `<span class="icone-emoji">${a.icone}</span>`;
      b.innerHTML = `${ic}<span class="icone-nom">${a.nom}</span>`;
      b.onclick = () => ouvrir(a.vue);
      t.appendChild(b);
    }
  }

  // ---------------------------------------------------------- Menu Démarrer
  const menu = {
    ouvert: false,
    basculer(force) {
      this.ouvert = force ?? !this.ouvert;
      $("menuDemarrer").classList.toggle("cache", !this.ouvert);
      $("boutonDemarrer").setAttribute("aria-expanded", String(this.ouvert));
      if (this.ouvert) { $("menuRecherche").value = ""; this.remplir(""); setTimeout(() => $("menuRecherche").focus(), 30); }
    },
    remplir(filtre) {
      const f = filtre.trim().toLowerCase();
      const z = $("menuApplis");
      z.innerHTML = "";
      const liste = [...APPLIS, { vue: "alex", icone: "🛠️", nom: "Espace Alex", sous: "Réglages techniques" }]
        .filter((a) => !f || (a.nom + " " + a.sous).toLowerCase().includes(f));
      for (const a of liste) {
        const b = document.createElement("button");
        b.className = "menu-appli";
        b.innerHTML = (a.image ? `<img src="${a.image}" alt="">` : `<span>${a.icone}</span>`) + `<span>${a.nom}</span>`;
        b.onclick = () => { this.basculer(false); ouvrir(a.vue); };
        z.appendChild(b);
      }
      if (!liste.length) z.innerHTML = `<span class="petit">Aucune appli ne correspond. Essaie de le demander à l'assistante !</span>`;
      const r = $("menuRecents");
      const docsRec = (A.documents() || []).slice(0, 4);
      r.innerHTML = docsRec.length ? "" : `<span class="petit">Tes derniers fichiers apparaîtront ici.</span>`;
      for (const d of docsRec) {
        const e = document.createElement("div");
        e.className = "recent";
        e.innerHTML = `<span>${d.icone || "📄"}</span><span class="recent-nom">${M.echapper(d.nom)}</span>`;
        r.appendChild(e);
      }
      const prenom = A.reglages().prenom || "Moi";
      $("menuNom").textContent = prenom;
      $("menuAvatar").textContent = prenom.charAt(0).toUpperCase();
    },
  };
  $("menuRecherche").addEventListener("input", (e) => menu.remplir(e.target.value));
  $("menuRecherche").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { const p = document.querySelector(".menu-appli"); if (p) p.click(); }
    if (e.key === "Escape") menu.basculer(false);
  });
  document.addEventListener("click", (e) => { if (menu.ouvert && !e.target.closest("#menuDemarrer")) menu.basculer(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && menu.ouvert) menu.basculer(false); });
  $("widgetAssistante").onclick = () => ouvrir("assistante");

  // -------------------------------------------------------- Mes documents
  const ICONES = { docx: "📄", doc: "📄", xlsx: "📊", xls: "📊", csv: "📊", pdf: "📕", png: "🖼️", jpg: "🖼️", jpeg: "🖼️", gif: "🖼️", webp: "🖼️", mp4: "🎬", webm: "🎬", txt: "📝", zip: "🗜️" };
  const taille = (o) => o == null ? "" : o < 1024 ? o + " o" : o < 1048576 ? Math.round(o / 1024) + " Ko" : (o / 1048576).toFixed(1).replace(".", ",") + " Mo";

  const docs = {
    chemin: [],
    mode: "documents",          // ou "corbeille"
    async afficher() {
      const corbeille = this.mode === "corbeille";
      $("docsTitre").innerHTML = corbeille ? `<img src="img/corbeille.png" alt="" class="titre-image"> Corbeille` : "📁 Mes documents";
      const e = Outils.etatDossier();
      $("docsBrancher").classList.toggle("cache", !!e.nom);
      $("docsReconnecter").classList.toggle("cache", !e.nom || e.pret);
      const pret = e.nom && e.pret;
      $("docsListe").classList.toggle("cache", !pret);
      ["docsHaut", "docsNouveau", "docsAjouter"].forEach((id) => { $(id).classList.toggle("cache", corbeille); $(id).disabled = !pret; });
      $("docsVider").classList.toggle("cache", !corbeille || !pret);
      $("docsHaut").disabled = !pret || !this.chemin.length;
      $("docsPied").textContent = corbeille
        ? "Les fichiers supprimés attendent ici. « Restaurer » les remet dans Mes documents."
        : "Astuce : glisse des fichiers de l'ordinateur dans cette fenêtre pour les copier sur la clé.";
      $("docsChemin").textContent = pret ? (corbeille ? [e.nom, Outils.CORBEILLE] : [e.nom, ...this.chemin]).join("  ›  ") : "";
      if (!pret) return;
      const l = $("docsListe");
      const chemin = corbeille ? Outils.CORBEILLE : this.chemin.join("/");
      let items;
      try {
        if (corbeille) await Outils.creerDossier(Outils.CORBEILLE);
        items = await Outils.entrees(chemin);
      } catch (err) { l.innerHTML = `<div class="vide">Impossible de lire ce dossier : ${M.echapper(err.message)}</div>`; return; }
      // La corbeille a sa propre icône sur le bureau : on ne la montre pas dans la liste.
      if (!corbeille && !this.chemin.length) items = items.filter((it) => !(it.dossier && it.nom === Outils.CORBEILLE));
      l.innerHTML = items.length ? "" : corbeille
        ? `<div class="vide">La corbeille est vide. 👍</div>`
        : `<div class="vide">Ce dossier est vide. Glisse des fichiers ici, ou clique sur « Ajouter des fichiers ».</div>`;
      for (const it of items) {
        const ext = it.nom.split(".").pop().toLowerCase();
        const ligne = document.createElement("div");
        ligne.className = "doc";
        ligne.setAttribute("role", "listitem");
        ligne.tabIndex = 0;
        ligne.innerHTML = `<span class="doc-icone">${it.dossier ? "📁" : ICONES[ext] || "📄"}</span>
          <span class="doc-nom">${M.echapper(it.nom)}</span>
          <span class="doc-info">${it.dossier ? "Dossier" : taille(it.taille)}</span>
          <span class="doc-info">${it.date ? new Date(it.date).toLocaleDateString("fr-CA") : ""}</span>
          <span class="doc-actions"></span>`;
        const act = ligne.querySelector(".doc-actions");
        const agir = async (fn, ok) => { try { await fn(); if (ok) $("docsPied").textContent = ok; } catch (err) { alert(err.message); } this.afficher(); };
        if (corbeille) {
          if (!it.dossier) act.appendChild(this.bouton("↩ Restaurer", () => agir(() => Outils.restaurer(it.nom), `✔ « ${it.nom} » est de retour dans Mes documents.`)));
        } else if (it.dossier) {
          const ouvrirDossier = () => { this.chemin.push(it.nom); this.afficher(); };
          ligne.ondblclick = ouvrirDossier;
          ligne.onkeydown = (ev) => ev.key === "Enter" && ouvrirDossier();
          act.appendChild(this.bouton("Ouvrir", ouvrirDossier));
          act.appendChild(this.bouton("🗑️", () => agir(() => Outils.supprimerDossierVide(chemin, it.nom)), "Supprimer ce dossier (s'il est vide)"));
        } else {
          const ouvrirFichier = async () => { const f = await Outils.fichierDuDossier(chemin, it.nom); Outils.telecharger(f, it.nom); };
          ligne.ondblclick = ouvrirFichier;
          act.appendChild(this.bouton("Ouvrir", ouvrirFichier, "Ouvre une copie dans Word, Excel ou la visionneuse"));
          if (/^(png|jpe?g|gif|webp|bmp|docx|xlsx|xls|txt|csv|md)$/.test(ext)) {
            act.appendChild(this.bouton("💬 À l'assistante", async () => {
              const f = await Outils.fichierDuDossier(chemin, it.nom);
              ouvrir("assistante");
              await A.ajouterFichiers([f]);
              A.ecrire(/^(png|jpe?g|gif|webp|bmp)$/.test(ext) ? "Regarde cette photo et dis-moi ce que tu vois." : "Lis ce document et fais-m'en un résumé.");
            }, "Envoyer ce fichier à l'assistante"));
          }
          act.appendChild(this.bouton("🗑️", () => agir(() => Outils.mettreALaCorbeille(chemin, it.nom), `« ${it.nom} » est dans la corbeille.`), "Mettre à la corbeille"));
        }
        l.appendChild(ligne);
      }
    },
    bouton(texte, action, titre) {
      const b = document.createElement("button");
      b.className = "bouton petit"; b.textContent = texte; if (titre) b.title = titre;
      b.onclick = (ev) => { ev.stopPropagation(); action(); };
      return b;
    },
    async copier(fichiers) {
      if (!fichiers.length || this.mode === "corbeille") return;
      try {
        const noms = await Outils.copierDans(this.chemin.join("/"), fichiers);
        $("docsPied").textContent = `✔ Copié sur la clé : ${noms.join(", ")}`;
      } catch (e) { $("docsPied").textContent = "Copie impossible : " + e.message; }
      this.afficher();
    },
  };

  $("docsChoisir").onclick = async () => {
    try { await Outils.choisirDossier(); } catch (e) { if (e.name !== "AbortError") alert(e.message); }
    docs.chemin = []; docs.afficher(); A.afficherDossier();
  };
  $("docsReconnecterBtn").onclick = async () => { try { await Outils.reconnecterDossier(); } catch {} docs.afficher(); A.afficherDossier(); };
  $("docsHaut").onclick = () => { docs.chemin.pop(); docs.afficher(); };
  $("docsVider").onclick = async () => {
    if (!confirm("Vider la corbeille ? Les fichiers seront effacés pour de bon.")) return;
    try { const n = await Outils.viderCorbeille(); $("docsPied").textContent = `Corbeille vidée (${n} élément${n > 1 ? "s" : ""}).`; } catch (e) { alert(e.message); }
    docs.afficher();
  };
  $("docsAjouter").onclick = () => $("docsFichiers").click();
  $("docsFichiers").onchange = (e) => { docs.copier([...e.target.files]); e.target.value = ""; };
  $("docsNouveau").onclick = async () => {
    const nom = prompt("Nom du nouveau dossier :", "Nouveau dossier");
    if (!nom) return;
    try { await Outils.creerDossier([...docs.chemin, nom].join("/")); } catch (e) { alert(e.message); }
    docs.afficher();
  };
  const zoneDocs = $("docsZone");
  zoneDocs.addEventListener("dragover", (e) => { e.preventDefault(); zoneDocs.classList.add("depot"); });
  zoneDocs.addEventListener("dragleave", (e) => { if (!zoneDocs.contains(e.relatedTarget)) zoneDocs.classList.remove("depot"); });
  zoneDocs.addEventListener("drop", (e) => { e.preventDefault(); zoneDocs.classList.remove("depot"); docs.copier([...e.dataTransfer.files]); });

  // ---------------------------------------------------------- Calculatrice
  const calc = {
    hist: JSON.parse(localStorage.getItem("calc-hist") || "[]"),
    calculer() {
      const v = $("calcEcran").value.trim();
      if (!v) { $("calcResultat").innerHTML = "&nbsp;"; return null; }
      try {
        const r = Outils.calculer(v);
        $("calcResultat").textContent = "= " + r.toLocaleString("fr-CA", { maximumFractionDigits: 6 });
        return r;
      } catch { $("calcResultat").textContent = "…"; return null; }
    },
    garder(ligne) {
      this.hist.unshift(ligne);
      this.hist = this.hist.slice(0, 30);
      try { localStorage.setItem("calc-hist", JSON.stringify(this.hist)); } catch {}
      this.afficherHist();
    },
    afficherHist() {
      $("calcHist").innerHTML = this.hist.length ? this.hist.map((h) => `<div>${M.echapper(h)}</div>`).join("") : `<span class="petit">Tes calculs apparaîtront ici.</span>`;
    },
    taxes(inclus) {
      const r = this.calculer();
      if (r === null) { $("calcDetail").textContent = "Écris d'abord un montant."; return; }
      const t = Outils.taxes(r, inclus);
      const f = (x) => Outils.argent.format(x);
      $("calcDetail").innerHTML = `<div>Avant taxes <strong>${f(t.avant)}</strong></div><div>TPS (5 %) <strong>${f(t.tps)}</strong></div><div>TVQ (9,975 %) <strong>${f(t.tvq)}</strong></div><div class="total">Total <strong>${f(t.total)}</strong></div>`;
      this.garder(`${f(r)} ${inclus ? "taxes incluses" : "+ taxes"} → avant ${f(t.avant)}, total ${f(t.total)}`);
    },
  };
  const TOUCHES = ["7", "8", "9", "÷", "4", "5", "6", "×", "1", "2", "3", "−", "0", ",", "%", "+", "(", ")", "⌫", "="];
  TOUCHES.forEach((k) => {
    const b = document.createElement("button");
    b.className = "bouton touche" + (k === "=" ? " principal" : "");
    b.textContent = k;
    b.onclick = () => {
      const e = $("calcEcran");
      if (k === "=") {
        const r = calc.calculer();
        if (r !== null) { calc.garder(`${e.value} = ${r.toLocaleString("fr-CA", { maximumFractionDigits: 6 })}`); e.value = String(r).replace(".", ","); }
      } else if (k === "⌫") e.value = e.value.slice(0, -1);
      else e.value += k === "−" ? "-" : k;
      calc.calculer();
      e.focus();
    };
    $("calcTouches").appendChild(b);
  });
  $("calcEcran").addEventListener("input", () => calc.calculer());
  $("calcEcran").addEventListener("keydown", (e) => {
    if (e.key === "Enter") document.querySelector(".touche.principal").click();
    if (e.key === "Escape") { e.target.value = ""; calc.calculer(); $("calcDetail").innerHTML = ""; }
  });
  $("calcPlusTaxes").onclick = () => calc.taxes(false);
  $("calcTaxesIncluses").onclick = () => calc.taxes(true);
  calc.afficherHist();

  // ------------------------------------------------------------ Bloc-notes
  const notes = {
    liste: JSON.parse(localStorage.getItem("notes") || "[]"),
    courante: null,
    sauver() { try { localStorage.setItem("notes", JSON.stringify(this.liste)); } catch {} },
    afficher() {
      if (!this.liste.length) this.nouvelle(false);
      if (!this.courante) this.courante = this.liste[0];
      const l = $("notesListe");
      l.innerHTML = "";
      for (const n of this.liste) {
        const e = document.createElement("div");
        e.className = "element" + (n === this.courante ? " actif" : "");
        e.tabIndex = 0;
        e.innerHTML = `<span class="element-texte">${M.echapper(n.titre || "Sans titre")}<span class="element-sous">${new Date(n.maj).toLocaleDateString("fr-CA")}</span></span><button class="suppr" title="Supprimer" aria-label="Supprimer">🗑️</button>`;
        e.onclick = (ev) => { if (ev.target.closest(".suppr")) return; this.courante = n; this.afficher(); };
        e.querySelector(".suppr").onclick = () => {
          if (!confirm(`Supprimer la note « ${n.titre || "Sans titre"} » ?`)) return;
          this.liste = this.liste.filter((x) => x !== n);
          if (this.courante === n) this.courante = null;
          this.sauver(); this.afficher();
        };
        l.appendChild(e);
      }
      $("noteTitre").value = this.courante.titre;
      $("noteTexte").value = this.courante.texte;
    },
    nouvelle(afficher = true) {
      const n = { titre: "", texte: "", maj: Date.now() };
      this.liste.unshift(n);
      this.courante = n;
      this.sauver();
      if (afficher) { this.afficher(); $("noteTitre").focus(); }
    },
    modifier() {
      if (!this.courante) return;
      this.courante.titre = $("noteTitre").value;
      this.courante.texte = $("noteTexte").value;
      this.courante.maj = Date.now();
      this.sauver();
      const actif = document.querySelector("#notesListe .element.actif .element-texte");
      if (actif) actif.firstChild.textContent = this.courante.titre || "Sans titre";
    },
  };
  $("noteTitre").addEventListener("input", () => notes.modifier());
  $("noteTexte").addEventListener("input", () => notes.modifier());
  $("notesNouvelle").onclick = () => notes.nouvelle();
  $("notesWord").onclick = async () => {
    const n = notes.courante;
    if (!n || !n.texte.trim()) { alert("La note est vide."); return; }
    const blob = await Outils.docxDepuisMarkdown(n.titre, n.texte);
    const f = await Outils.enregistrer(blob, Outils.nomPropre(n.titre || "Note", "docx"));
    A.noterDocument({ ...f, icone: "📄" });
    alert(`Document Word créé : ${f.nom}\n(dans ${f.ou})`);
  };
  $("notesAssistante").onclick = () => {
    const n = notes.courante;
    if (!n || !n.texte.trim()) { alert("Écris d'abord quelque chose dans la note."); return; }
    ouvrir("assistante");
    A.ecrire(`Améliore ce texte (fautes, clarté, ton professionnel) et redonne-le-moi prêt à utiliser :\n\n${n.texte}`, true);
  };

  // --------------------------------------------------------------- Affiches
  let affichePhoto = null;
  let afficheBlob = null;
  const form = $("afficheForm");
  form.photo.onchange = () => {
    const f = form.photo.files[0];
    if (!f) { affichePhoto = null; return; }
    const r = new FileReader();
    r.onload = () => { affichePhoto = r.result; };
    r.readAsDataURL(f);
  };
  function donneesAffiche() {
    const v = (n) => form[n].value.trim();
    return {
      accroche: v("accroche"), titre: v("titre"), sous_titre: v("sous_titre"), prix: v("prix"), appel: v("appel"),
      points: v("points").split("\n").map((s) => s.trim()).filter(Boolean),
      couleur: form.couleur.value, format: form.format.value, photo: affichePhoto ? 1 : undefined,
    };
  }
  async function apercuAffiche() {
    const d = donneesAffiche();
    if (!d.titre) { form.titre.focus(); form.titre.reportValidity(); return null; }
    afficheBlob = await Outils.creerAffiche(d, affichePhoto ? [affichePhoto] : [], A.reglages().coordonnees);
    const z = $("afficheApercuZone");
    z.innerHTML = "";
    const img = new Image();
    img.src = URL.createObjectURL(afficheBlob);
    img.alt = "Aperçu de l'affiche";
    z.appendChild(img);
    return afficheBlob;
  }
  $("afficheApercu").onclick = apercuAffiche;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const b = await apercuAffiche();
    if (!b) return;
    const f = await Outils.enregistrer(b, Outils.nomPropre("Affiche " + form.titre.value.trim(), "png"));
    A.noterDocument({ ...f, icone: "🖼️" });
    const note = document.createElement("div");
    note.className = "petit";
    note.style.marginTop = "8px";
    note.textContent = `✔ Enregistrée : ${f.nom} (dans ${f.ou})`;
    $("afficheApercuZone").appendChild(note);
  };

  // ------------------------------------------------------------------ Guide
  const GUIDE = [
    { icone: "👋", titre: "Bienvenue dans ton mini-ordinateur", vue: null, etapes: [
      "Tout ce qu'il y a ici fonctionne <strong>sur cet ordinateur, sans internet</strong>. Rien de ce que tu écris ne sort d'ici.",
      "Le <strong>bureau</strong> montre tes applications. Clique sur une grosse icône pour l'ouvrir.",
      "La <strong>barre du bas</strong> fonctionne comme dans Windows : clique sur une icône pour passer d'une appli à l'autre, et sur le petit logo à gauche pour revenir au bureau.",
    ] },
    { icone: "💬", titre: "Parler à l'assistante", vue: "assistante", etapes: [
      "Écris ta demande en bas, comme un texto à une collègue, puis appuie sur <strong>Entrée</strong>.",
      "Les boutons de l'accueil te donnent des idées : courriel à un client, rappel de paiement, corriger un texte…",
      "Sous chaque réponse : <strong>📋 Copier</strong> pour coller ailleurs (Outlook, Facebook), <strong>🔊 Écouter</strong> pour l'entendre, <strong>📄 Word</strong> et <strong>📊 Excel</strong> pour en faire un fichier.",
      "Pour lui montrer une photo ou un document, clique sur <strong>📎</strong>, ou colle une image avec <strong>Ctrl + V</strong>.",
      "Elle peut se tromper : <strong>relis</strong> avant d'envoyer quelque chose d'important.",
    ] },
    { icone: "📄", titre: "Créer des lettres, tableaux, affiches et vidéos", vue: "assistante", etapes: [
      "Demande-le simplement : « Fais-moi une lettre Word pour… », « Fais un tableau Excel des commandes », « Fais une affiche pour la promo d'hiver », « Fais une vidéo avec mes photos ».",
      "Le fichier est créé tout seul et rangé dans <strong>Mes documents</strong>. Le bouton <strong>Ouvrir</strong> l'ouvre dans Word, Excel ou la visionneuse.",
      "Les <strong>calculs et les taxes</strong> sont faits par l'ordinateur, pas par l'IA : ils sont exacts.",
    ] },
    { icone: "🧮", titre: "Calculatrice avec taxes", vue: "calcul", etapes: [
      "Écris un calcul (ex. <em>149,99 × 2</em>) avec le clavier ou les touches.",
      "<strong>＋ Taxes</strong> ajoute la TPS et la TVQ. <strong>Taxes incluses ?</strong> retrouve le montant avant taxes.",
      "Tes derniers calculs restent dans l'historique.",
    ] },
    { icone: "📝", titre: "Bloc-notes", vue: "notes", etapes: [
      "Écris tes notes et brouillons : c'est <strong>enregistré tout seul</strong>.",
      "<strong>💬 Améliorer avec l'assistante</strong> corrige et embellit ton texte. <strong>📄 Mettre dans Word</strong> en fait un document.",
    ] },
    { icone: "🖼️", titre: "Créateur d'affiches", vue: "affiche", etapes: [
      "Remplis le titre, le prix et les points forts, ajoute une photo du produit.",
      "Choisis la couleur et le format (Facebook ou à imprimer), puis <strong>👀 Aperçu</strong>.",
      "<strong>💾 Enregistrer</strong> met l'affiche dans Mes documents, prête à publier ou à imprimer.",
    ] },
    { icone: "📁", titre: "Mes documents et la corbeille", vue: "documents", etapes: [
      "La première fois, clique sur <strong>Choisir le dossier</strong> et sélectionne <strong>Mes documents</strong> sur la clé.",
      "<strong>📥 Ajouter des fichiers</strong> copie des fichiers de l'ordinateur vers la clé. Tu peux aussi les <strong>glisser</strong> dans la fenêtre.",
      "Tu retrouves aussi ce dossier dans l'<strong>Explorateur Windows</strong> : ouvre la clé, puis « Mes documents ».",
      "Le bouton 🗑️ met un fichier à la <strong>corbeille</strong>. Dans la Corbeille, <strong>↩ Restaurer</strong> le récupère ; il n'est effacé que si tu vides la corbeille.",
    ] },
    { icone: "⚙️", titre: "Réglages", vue: "reglages", etapes: [
      "<strong>Thème</strong> : clair, sombre, ou automatique (clair le jour, sombre le soir).",
      "Choisis ta <strong>couleur</strong> et ton <strong>fond d'écran</strong>.",
      "Ajoute ta <strong>signature</strong> de courriel et les <strong>coordonnées</strong> du magasin : l'assistante s'en servira.",
      "Coche <strong>Lire les réponses à voix haute</strong> pour tout entendre. <strong>A− / A+</strong> dans l'assistante change la grosseur du texte.",
    ] },
    { icone: "🛟", titre: "Si quelque chose ne marche pas", vue: null, etapes: [
      "Ferme la fenêtre, puis double-clique de nouveau sur <strong>Démarrer l'assistante</strong> sur la clé.",
      "Si ça continue : redémarre l'ordinateur et réessaie.",
      "Avant de retirer la clé, <strong>ferme la fenêtre</strong> et attends quelques secondes.",
      "Et sinon… appelle Alex ! 😊",
    ] },
  ];
  function afficherGuide() {
    const g = $("guide");
    g.innerHTML = "";
    GUIDE.forEach((s, i) => {
      const c = document.createElement("article");
      c.className = "guide-carte";
      c.innerHTML = `<div class="guide-num">${i + 1}</div><h2><span>${s.icone}</span> ${s.titre}</h2><ol>${s.etapes.map((e) => `<li>${e}</li>`).join("")}</ol>`;
      if (s.vue) {
        const b = document.createElement("button");
        b.className = "bouton"; b.textContent = "Essayer →";
        b.onclick = () => ouvrir(s.vue);
        c.appendChild(b);
      }
      g.appendChild(c);
    });
  }
  afficherGuide();
  $("guideFini").onclick = () => { try { localStorage.setItem("guide-vu", "1"); } catch {} ouvrir("bureau"); };

  // ----------------------------------------------------------- Espace Alex
  const VERSION = "1.0 — octobre 2026";
  const alex = {
    async moteur() {
      const z = $("alexMoteur");
      try {
        const h = await fetch("/health", { cache: "no-store" });
        let props = {};
        try { props = await (await fetch("/props", { cache: "no-store" })).json(); } catch {}
        const modele = String(props.model_path || props.default_generation_settings?.model || "").split(/[\\/]/).pop() || "inconnu";
        const ctx = props.default_generation_settings?.n_ctx || props.n_ctx || "?";
        const vision = props.modalities?.vision ? "oui" : (props.modalities ? "non" : "?");
        z.innerHTML = h.ok
          ? `<div>🟢 <strong>En marche</strong></div><div>Modèle : <code>${M.echapper(modele)}</code></div><div>Contexte : ${ctx} jetons · Vision : ${vision}</div>`
          : `<div>🟡 Le moteur se réveille (code ${h.status})</div>`;
      } catch { z.innerHTML = "<div>🔴 Moteur arrêté — relancer « Démarrer l'assistante »</div>"; }
    },
    afficher() {
      const a = A.avance();
      $("alexTemp").value = a.temperature; $("alexTempVal").textContent = Number(a.temperature).toFixed(2);
      $("alexMax").value = a.maxTokens; $("alexMemoire").value = a.messagesGardes; $("alexInstructions").value = a.instructions;
      $("alexInfos").innerHTML = `Version de la clé : ${VERSION}<br>Navigateur : ${M.echapper(navigator.userAgent.match(/Edg\/[\d.]+|Chrome\/[\d.]+/)?.[0] || "?")}<br>Conversations : ${A.conversations().length} · Documents créés : ${(A.documents() || []).length}<br>Fait avec amour par Alex — Produit du Québec.`;
      this.moteur();
    },
  };
  $("boutonAlex").onclick = () => ouvrir("alex");
  $("alexRafraichir").onclick = () => alex.moteur();
  $("alexTemp").oninput = () => ($("alexTempVal").textContent = Number($("alexTemp").value).toFixed(2));
  $("alexEnregistrer").onclick = () => {
    const v = { temperature: parseFloat($("alexTemp").value), maxTokens: parseInt($("alexMax").value, 10) || 1500,
      messagesGardes: Math.min(40, Math.max(2, parseInt($("alexMemoire").value, 10) || 12)), instructions: $("alexInstructions").value };
    try { localStorage.setItem("avance", JSON.stringify(v)); alert("Réglages enregistrés ✔"); } catch { alert("Enregistrement impossible."); }
  };
  $("alexDefaut").onclick = () => { try { localStorage.removeItem("avance"); } catch {} alex.afficher(); };
  const CLES = ["conversations", "documents", "reglages", "notes", "calc-hist", "avance", "guide-vu"];
  $("alexExporter").onclick = () => {
    const data = { app: "mon-assistante", version: VERSION, date: new Date().toISOString(), donnees: {} };
    for (const k of CLES) { const v = localStorage.getItem(k); if (v !== null) data.donnees[k] = v; }
    const nom = `Sauvegarde assistante ${new Date().toLocaleDateString("fr-CA")}.json`;
    Outils.telecharger(new Blob([JSON.stringify(data)], { type: "application/json" }), nom);
  };
  $("alexImporter").onclick = () => $("alexFichier").click();
  $("alexFichier").onchange = async (e) => {
    const f = e.target.files[0]; e.target.value = "";
    if (!f) return;
    try {
      const data = JSON.parse(await f.text());
      if (data.app !== "mon-assistante" || !data.donnees) throw new Error("Ce fichier n'est pas une sauvegarde de l'assistante.");
      if (!confirm("Remplacer les conversations, notes et réglages actuels par cette sauvegarde ?")) return;
      for (const [k, v] of Object.entries(data.donnees)) if (CLES.includes(k)) localStorage.setItem(k, v);
      location.reload();
    } catch (err) { alert(err.message); }
  };
  $("alexGuide").onclick = () => { try { localStorage.removeItem("guide-vu"); } catch {} alert("Le guide s'affichera au prochain démarrage."); };
  $("alexEffacerConv").onclick = () => {
    if (!confirm("Effacer toutes les conversations ? (Les fichiers dans Mes documents ne sont pas touchés.)")) return;
    localStorage.removeItem("conversations"); location.reload();
  };
  $("alexToutEffacer").onclick = () => {
    if (!confirm("Tout remettre à neuf : conversations, notes, réglages… (Les fichiers dans Mes documents restent.) Continuer ?")) return;
    for (const k of CLES) localStorage.removeItem(k);
    location.reload();
  };

  // ----------------------------------------------------------------- départ
  barreTaches();
  tuiles();
  horloge();
  setInterval(horloge, 15000);
  let dejaVu = false;
  try { dejaVu = localStorage.getItem("guide-vu") === "1"; } catch {}
  ouvrir(dejaVu ? "bureau" : "guide");
  if (!dejaVu) try { localStorage.setItem("guide-vu", "1"); } catch {}
})();
