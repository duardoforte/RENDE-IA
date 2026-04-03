    const fullText = "Encontrando a melhor opção de renda fixa para o seu perfil conservador...";
    const typedText = document.getElementById("typed-text");
    const subtitle = document.getElementById("subtitle");
    const buttons = document.getElementById("buttons");
    const panel = document.getElementById("panel");
    const soundButton = document.getElementById("soundButton");
    const soundIcon = document.getElementById("soundIcon");

    let index = 0;

    function typeEffect() {
      if (index < fullText.length) {
        typedText.textContent += fullText.charAt(index);
        index++;
        setTimeout(typeEffect, 32);
      } else {
        subtitle.classList.add("show");
        buttons.classList.add("show");
        setTimeout(() => {
          panel.classList.add("show");
        }, 250);
      }
    }

    typeEffect();

    let soundOn = true;

    soundButton.addEventListener("click", function () {
      soundOn = !soundOn;

      if (soundOn) {
        soundButton.setAttribute("aria-label", "Desativar som");
        soundButton.setAttribute("title", "Som ativado");
        soundIcon.innerHTML = `
          <path d="M11 5L6 9H3V15H6L11 19V5Z"></path>
          <path d="M15 9C16.2 10 17 11.3 17 12.5C17 13.7 16.2 15 15 16"></path>
          <path d="M17.5 6.5C19.5 8.2 21 10.2 21 12.5C21 14.8 19.5 16.8 17.5 18.5"></path>
        `;
      } else {
        soundButton.setAttribute("aria-label", "Ativar som");
        soundButton.setAttribute("title", "Som desativado");
        soundIcon.innerHTML = `
          <path d="M11 5L6 9H3V15H6L11 19V5Z"></path>
          <line x1="4" y1="4" x2="20" y2="20"></line>
        `;
      }
    });