const suspectList = document.getElementById("suspectList");
const selectedSuspect = document.getElementById("selectedSuspect");
const messages = document.getElementById("messages");
const messageInput = document.getElementById("messageInput");
const sendButton = document.getElementById("sendButton");
const accuseButton = document.getElementById("accuseButton");
const statusText = document.getElementById("statusText");
const autopsyButton = document.querySelector(".autopsy-button");
const autopsyModal = document.getElementById("autopsyModal");
const closeAutopsy = document.getElementById("closeAutopsy");
const verdictModal = document.getElementById("verdictModal");
const verdictContent = document.getElementById("verdictContent");
const verdictTitle = document.getElementById("verdictTitle");
const verdictSubtitle = document.getElementById("verdictSubtitle");
const verdictMainText = document.getElementById("verdictMainText");
const verdictStamp = document.getElementById("verdictStamp");
const overlayStamp = document.getElementById("overlayStamp");
const restartButton = document.getElementById("restartButton");
const introModal = document.getElementById("introModal");
const acceptCaseButton = document.getElementById("acceptCaseButton");

let suspects = [];
let activeSuspectId = null;
let sessionId = localStorage.getItem("detectiveSessionId") || crypto.randomUUID();
localStorage.setItem("detectiveSessionId", sessionId);

function renderSuspects() {
  suspectList.innerHTML = "";
  suspects.forEach((suspect) => {
    const item = document.createElement("div");
    item.className = "suspect-item";
    if (suspect.id === activeSuspectId) {
      item.classList.add("selected");
    }
    const emoji = suspect.role.includes("lékař") ? "👨‍⚕️" : suspect.role.includes("milenka") ? "👩" : "🕵️";
    item.innerHTML = `
      <div class="suspect-name">${emoji} ${suspect.name}</div>
      <div class="suspect-role">${suspect.role}</div>
    `;
    item.addEventListener("click", () => selectSuspect(suspect.id));
    suspectList.appendChild(item);
  });
}

function typeText(element, text, speed = 50) {
  element.textContent = '';
  let i = 0;
  const timer = setInterval(() => {
    if (i < text.length) {
      element.textContent += text.charAt(i);
      i++;
    } else {
      clearInterval(timer);
    }
  }, speed);
}

function selectSuspect(id) {
  activeSuspectId = id;
  const suspect = suspects.find((item) => item.id === id);
  selectedSuspect.textContent = suspect
    ? `${suspect.name} • ${suspect.role}`
    : "Vyberte podezřelého vlevo.";
  renderSuspects();
  messages.innerHTML = "";
  typeText(statusText, "Vybrán nový podezřelý. Ptejte se pečlivě.");
}

function appendMessage(text, role) {
  const row = document.createElement("div");
  row.className = `message ${role}`;
  const label = role === "user" ? "Detektiv:" : `${suspects.find((s) => s.id === activeSuspectId)?.name || "Podezřelý"}:`;
  row.innerHTML = `
    <div class="message-label">${label}</div>
    <div class="message-content"></div>
  `;
  messages.appendChild(row);
  messages.scrollTop = messages.scrollHeight;

  // Typewriter effect
  const contentDiv = row.querySelector('.message-content');
  let i = 0;
  const timer = setInterval(() => {
    if (i < text.length) {
      contentDiv.textContent += text.charAt(i);
      i++;
    } else {
      clearInterval(timer);
    }
  }, 30);
}



async function fetchPrompts() {
  try {
    const response = await fetch("/api/suspects");
    suspects = await response.json();
    renderSuspects();
  } catch (error) {
    console.error("Chyba při načítání podezřelých:", error);
    statusText.textContent = "Chyba: Nepodařilo se načíst podezřelé.";
  }
}

async function postChat() {
  if (!activeSuspectId) {
    statusText.textContent = "Nejdříve vyberte podezřelého.";
    return;
  }

  const text = messageInput.value.trim();
  if (!text) {
    statusText.textContent = "Zadejte zprávu.";
    return;
  }

  appendMessage(`Hráč: ${text}`, "user");
  messageInput.value = "";
  typeText(statusText, "Čekání na odpověď...");

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        suspect_id: activeSuspectId,
        message: text,
      }),
    });

    if (!response.ok) {
      throw new Error("Chyba serveru");
    }

    const data = await response.json();
    appendMessage(`${suspects.find((s) => s.id === activeSuspectId).name}: ${data.response}`, "suspect");
    typeText(statusText, "Odpověď přijata.");
  } catch (error) {
    typeText(statusText, "Nezdařilo se poslat zprávu.");
  }
}

async function accuseSuspect() {
  if (!activeSuspectId) {
    statusText.textContent = "Nejdříve vyberte podezřelého.";
    return;
  }

  const suspect = suspects.find((item) => item.id === activeSuspectId);
  
  // Dim screen effect
  const caseFile = document.querySelector(".case-file");
  caseFile.style.animation = "none";
  caseFile.offsetHeight; // Reflow
  caseFile.style.animation = "dimScreen 0.6s ease-in-out";

  // Prepare verdict based on suspect ID
  let isWon = false;
  let verdictText = "";

  if (activeSuspectId === "1") {
    // VIKTOR DOLEŽAL = SPRÁVNÁ ODPOVĚĎ
    isWon = true;
    verdictContent.className = "verdict-content won";
    verdictTitle.className = "verdict-title won";
    verdictTitle.textContent = "PŘÍPAD UZAVŘEN";
    verdictSubtitle.textContent = "ROZSUDEK NEJVYŠŠÍHO SOUDU";
    verdictStamp.textContent = "VINEN";
    verdictStamp.className = "verdict-stamp won";
    overlayStamp.textContent = "VINEN";
    overlayStamp.style.color = "rgba(34, 139, 34, 0.12)";
    
    verdictText = `
    <p>Detektive, váš instinkt byl neomylný.</p>
    <p><strong>Viktor Doležal</strong>, osobní lékař Richard Bohatého, byl shledán vinným vraždu nejprve stupně.</p>
    <p>Důkazy byly jasné: chirurgická přesnost bodného zranění, přístup k sedativům a motivace – <strong>15 milionů korun zpronevěřených na falešný výzkum</strong>. Doležal vám chladně lhál o svých kvalifikacích, ale jeho sebevědomí jej zradilo. Ve své aroganci si myslel, že detektivní sbor je příliš hloupý na to, aby rozklíčoval jeho dokonalý plán.</p>
    <p>Viktor je zatčen. Jeho lékařská licence je zrušena. Bohatého rodina dostane svůdyhodné pojistné. A ty, jsi teď <strong>legendou policejního sboru</strong>. Tvá jména si budou pamatovat v akademii na příštích generace detektivů.</p>
    <p style="color: #228B22; font-weight: bold; margin-top: 20px;">VYŠETŘOVÁNÍ UZAVŘENO – PŘÍPAD VYŘEŠEN</p>
    `;
  } else if (activeSuspectId === "2") {
    // EVA HORÁKOVÁ = ŠPATNÁ ODPOVĚĎ
    isWon = false;
    verdictContent.className = "verdict-content lost";
    verdictTitle.className = "verdict-title lost";
    verdictTitle.textContent = "JUSTIČNÍ OMYL";
    verdictSubtitle.textContent = "STŘET SE SOUDNÍM SYSTÉMEM";
    verdictStamp.textContent = "NEVINEN";
    verdictStamp.className = "verdict-stamp lost";
    overlayStamp.textContent = "NEVINEN";
    overlayStamp.style.color = "rgba(139, 0, 0, 0.12)";
    
    verdictText = `
    <p>Detektive, chybil jste.</p>
    <p><strong>Eva Horáková</strong> byla obviněna z vraždy Richard Bohatého. Soud však nenalezl nezvratné důkazy přímo proti ní. Její právník – slavný pan JUDr. Novotný – ji bravurně obhájil. Eva byla <strong>zproštěna viny</strong> a propuštěna.</p>
    <p>Zatímco se Eva vrátila do života, šíří o tobě, nezodpovědném detektivovi, který skoro zničil její reputaci. Ona samá si najímá právníky, aby podala <strong>kvůli vám žalobu na odškodnění</strong>.</p>
    <p>Ale to není nejhorší. Skutečný vrah – <strong>Viktor Doležal</strong> – mezitím zmizeli za hranice. Policejní hlídka ho našla v Srbsku, ale bez vystoupení. Údajně pracuje v soukromé klinice pod jiným jménem, kde pokračuje v "lékařské praxi".</p>
    <p style="color: #8b0000; font-weight: bold; margin-top: 20px;">KARIÉRA UKONČENA – MÍSTO V ODDĚLENÍ ZRUŠENO</p>
    `;
  } else if (activeSuspectId === "3") {
    // TOMÁŠ KRÁL = ŠPATNÁ ODPOVĚĎ
    isWon = false;
    verdictContent.className = "verdict-content lost";
    verdictTitle.className = "verdict-title lost";
    verdictTitle.textContent = "JUSTIČNÍ OMYL";
    verdictSubtitle.textContent = "TRAGÉDIE CHYBNÉ VYŠETŘOVÁNÍ";
    verdictStamp.textContent = "NEVINEN";
    verdictStamp.className = "verdict-stamp lost";
    overlayStamp.textContent = "NEVINEN";
    overlayStamp.style.color = "rgba(139, 0, 0, 0.12)";
    
    verdictText = `
    <p>Detektive, váš verdikt byl fatální chyba.</p>
    <p><strong>Tomáš Král</strong>, obchodní rival, byl obviněn z vraždy Richard Bohatého. Soud však zjistil, že jeho přítomnost v knihovně lze vysvětlit jeho vlastnímBusinessem – přišel si vyzvednout dlužné peníze a našel Richarda již mrtvého.</p>
    <p>Záchod Králův právník provedl fantasticky. Díky vaší chybě a nedostačujícím důkazům byl <strong>zproštěn všech obvinění</strong>. Nyní podává <strong>masivní žalobu</strong> na policejní sbor za nesprávné podezření a odškodňování ve výši 40 milionů korun.</p>
    <p>Mezitím se skutečný vrah – <strong>Viktor Doležal</strong> – stal uprchlíkem. Má lékařskou licenci a potřebný přístup k lékům. <strong>Tři další osoby zemřely podobným způsobem</strong> v následujících měsících. Novináři si říkají "doktor Smrt".</p>
    <p style="color: #8b0000; font-weight: bold; margin-top: 20px;">VYŠETŘOVÁNÍ ZNIČENO – SKUTEČNÝ VRAH STÁLE SVOBODNÝ</p>
    `;
  }

  verdictMainText.innerHTML = verdictText;

  // Wait a moment, then show verdict
  setTimeout(() => {
    verdictModal.classList.add("show");
    document.body.style.overflow = "hidden";
  }, 700);
}

sendButton.addEventListener("click", postChat);
accuseButton.addEventListener("click", accuseSuspect);

// Restart button - reload page
restartButton.addEventListener("click", () => {
  location.reload();
});

// Autopsy modal handlers
autopsyButton.addEventListener("click", () => {
  autopsyModal.classList.add("active");
  autopsyModal.style.display = "flex";
  document.body.style.overflow = "hidden";
});

closeAutopsy.addEventListener("click", () => {
  autopsyModal.classList.remove("active");
  autopsyModal.style.display = "none";
  document.body.style.overflow = "auto";
});

autopsyModal.addEventListener("click", (e) => {
  if (e.target === autopsyModal) {
    closeAutopsy.click();
  }
});

// Verdict modal - close on click outside
verdictModal.addEventListener("click", (e) => {
  if (e.target === verdictModal) {
    // Do nothing - prevent easy closing of verdict
  }
});

// Intro modal handlers
window.addEventListener("load", () => {
  // Show intro modal immediately on page load
  introModal.style.display = "flex";
  document.body.style.overflow = "hidden";
});

acceptCaseButton.addEventListener("click", () => {
  // Fade out intro modal
  introModal.classList.add("fade-out");
  document.body.style.overflow = "auto";

  // Remove modal from DOM after animation
  setTimeout(() => {
    introModal.style.display = "none";
  }, 500);
});

fetchPrompts();
