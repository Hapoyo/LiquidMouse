// Liquid Mouse — client, 2/4: touchpad, menu, tastiera del telefono.
//
// Parte del client diviso in quattro script (vedi app-core.js). Qui non si
// anima mai sul percorso del cursore: ogni millisecondo è latenza.

    // --- SENSIBILITA' CURSORE ---
    // Valore salvato in localStorage, applicato lato client prima dell'invio
    // Valore da localStorage non fidato: vuoto, NaN o fuori scala (una versione
    // vecchia, un salvataggio corrotto) lascerebbe il cursore fermo o impazzito.
    const SENS_MIN = 0.5, SENS_MAX = 4.0, SENS_DEFAULT = 1.8;
    let sensitivity = parseFloat(localStorage.getItem('lm_sensitivity'));
    if (!(sensitivity >= SENS_MIN && sensitivity <= SENS_MAX)) sensitivity = SENS_DEFAULT;

    // --- MOVIMENTO CURSORE ---
    let moveX = 0, moveY = 0, isMoving = false;
    // Resto sub-pixel non ancora spedito, in unita' gia' moltiplicate per
    // la sensibilita'. Vale sempre meno di un pixel per asse.
    let pendingX = 0, pendingY = 0;
    let twoFingerScrollAcc = 0;
    let twoFingerScrollAccX = 0;   // scroll orizzontale, stessa logica del verticale

    // --- GESTI: contratto (estratto ed eseguito da tests con node) ---
    // Decisioni pure dei gesti del touchpad, senza DOM né timer: il resto sta
    // nei gestori touch qui sotto, che non animano nulla (latenza del cursore).
    const MULTI_TAP_MAX_MS = 300;    // più largo del tap a un dito: le dita non atterrano insieme
    const MULTI_TAP_MAX_MOVE = 14;   // px di spostamento oltre cui non è più un tap
    const DRAG_WINDOW_MS = 300;      // secondo tocco entro questo tempo dal tap = tap-e-trascina
    const DRAG_NEAR_PX = 40;         // ...e abbastanza vicino al primo
    const SCROLL_GAIN = 0.375;
    // Pulsante prodotto da un gesto a più dita finito: due dita = destro, tre =
    // centrale; null se è durato troppo o le dita si sono mosse (era uno scroll).
    function multiTapButton(maxTouches, durationMs, maxMovePx) {
        if (maxTouches < 2 || durationMs >= MULTI_TAP_MAX_MS || maxMovePx > MULTI_TAP_MAX_MOVE) return null;
        return maxTouches === 2 ? 'right' : (maxTouches === 3 ? 'middle' : null);
    }
    // Il tocco che inizia ora può diventare un trascinamento col sinistro premuto?
    function dragArmed(lastTapEnd, now, distPx, dragLocked) {
        return !dragLocked && lastTapEnd > 0 && (now - lastTapEnd) < DRAG_WINDOW_MS && distPx <= DRAG_NEAR_PX;
    }
    // Scroll a due dita da uno spostamento del punto medio. Positivo = su (v) e
    // verso destra (h), come il verticale di sempre ("naturale": il contenuto
    // segue le dita). Vince l'asse dominante: il tremolio dell'altro si scarta,
    // salvo un vero movimento diagonale.
    function scrollDelta(dx, dy) {
        const ax = Math.abs(dx), ay = Math.abs(dy);
        const forte = Math.max(ax, ay);
        return {
            v: ay < forte * 0.6 ? 0 : dy * SCROLL_GAIN,
            h: ax < forte * 0.6 ? 0 : -dx * SCROLL_GAIN,
        };
    }
    // --- fine contratto ---

    // Invio coalescizzato una volta per frame, ma schedulato SOLO quando c'è
    // input pendente. Da fermo non gira alcun loop a 60fps → meno CPU/batteria
    // sul telefono e nessun risveglio inutile. Comportamento identico in movimento.
    let sendScheduled = false;
    function flushSend() {
        sendScheduled = false;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        if (isMoving && (moveX !== 0 || moveY !== 0)) {
            // Il resto dell'arrotondamento va conservato, non buttato via
            // (lo scroll qui sotto lo fa gia'). Prima, con il dito lento,
            // moveX*sensitivity valeva p.es. 0.4, arrotondava a 0 e quel 0.4
            // spariva: il cursore non si muoveva finche' non si accelerava.
            // L'accumulatore e' gia' in unita' di output, cosi' non serve
            // ridividere per sensitivity (che da localStorage potrebbe
            // arrivare 0 o NaN).
            pendingX += moveX * sensitivity;
            pendingY += moveY * sensitivity;
            moveX = 0; moveY = 0; isMoving = false;
            const sx = Math.round(pendingX), sy = Math.round(pendingY);
            if (sx !== 0 || sy !== 0) {
                ws.send(JSON.stringify({ type: 'move', x: sx, y: sy }));
                pendingX -= sx; pendingY -= sy;
            }
        }
        // Verticale e orizzontale viaggiano nello stesso messaggio; ognuno solo
        // se non nullo, quindi il verticale puro resta {type, amount} come prima.
        const amount = Math.abs(twoFingerScrollAcc) >= 1 ? Math.round(twoFingerScrollAcc / 1.5) : 0;
        const hAmount = Math.abs(twoFingerScrollAccX) >= 1 ? Math.round(twoFingerScrollAccX / 1.5) : 0;
        if (amount !== 0 || hAmount !== 0) {
            const msg = { type: 'scroll' };
            if (amount !== 0) { msg.amount = amount; twoFingerScrollAcc -= amount * 1.5; }
            if (hAmount !== 0) { msg.h = hAmount; twoFingerScrollAccX -= hAmount * 1.5; }
            ws.send(JSON.stringify(msg));
        }
    }
    function scheduleSend() {
        if (!sendScheduled) { sendScheduled = true; requestAnimationFrame(flushSend); }
    }

    const pad = document.getElementById('touchpad');
    let lastX = 0, lastY = 0, touchActive = false;
    let twoFingerLastY = 0;

    // --- GESTI: tap, tap-e-trascina, due/tre dita, long-press ---
    // Un dito: tap = click sinistro, tap seguito da un tocco con movimento =
    // trascinamento (sinistro premuto), pressione lunga = click destro. Due dita:
    // scroll (verticale e orizzontale) o, se è un tap, click destro. Tre dita: tap
    // = click centrale. Le decisioni pure sono nel blocco "GESTI: contratto".
    const TAP_MAX_MS   = 200;
    const TAP_MAX_MOVE = 10;
    const LONG_PRESS_MS = 650;

    let tapStartTime = 0, tapStartX = 0, tapStartY = 0;
    let tapMoved = false, longPressTimer = null;
    // Gesto in corso (dal primo dito giù all'ultimo su): dita massime, spostamento
    // massimo di ciascuna dal punto di partenza, inizio.
    let gestureStart = 0, gestureMaxTouches = 0, gestureMaxMove = 0;
    const gestureOrigin = {};
    let twoFingerLastX = 0;
    // Tap-e-trascina: fine/posizione dell'ultimo tap a un dito, e stato del trascinamento.
    let lastTapEnd = 0, lastTapX = 0, lastTapY = 0;
    let dragCandidate = false, tapDragging = false;

    function resetGesture() {
        gestureMaxTouches = 0; gestureMaxMove = 0;
        for (const k in gestureOrigin) delete gestureOrigin[k];
        dragCandidate = false;
    }

    function endTapDrag() {
        if (!tapDragging) return;
        tapDragging = false;
        sendDrag('up');
    }

    pad.addEventListener('touchstart', (e) => {
        e.preventDefault();

        if (e.touches.length === 1) {
            // Primo dito di un nuovo gesto.
            resetGesture();
            gestureStart = Date.now();
        }
        gestureMaxTouches = Math.max(gestureMaxTouches, e.touches.length);
        for (const t of e.changedTouches) gestureOrigin[t.identifier] = { x: t.clientX, y: t.clientY };

        if (e.touches.length >= 2) {
            // Più dita: prepara scroll, disabilita movimento cursore. Un
            // trascinamento in corso finisce (il secondo dito non è un suo gesto).
            endTapDrag();
            dragCandidate = false;
            twoFingerLastX = (e.touches[0].clientX + e.touches[1].clientX) / 2;
            twoFingerLastY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
            touchActive = false;
            clearTimeout(longPressTimer);
            tapStartTime = 0;
            return;
        }

        touchActive = true;
        lastX = e.touches[0].clientX;
        lastY = e.touches[0].clientY;
        moveX = 0; moveY = 0;

        tapStartTime = Date.now();
        tapStartX = lastX;
        tapStartY = lastY;
        tapMoved = false;
        dragCandidate = dragArmed(lastTapEnd, tapStartTime,
                                  Math.hypot(lastX - lastTapX, lastY - lastTapY), locks.drag);

        longPressTimer = setTimeout(() => {
            if (!tapMoved) {
                sendClick('right');
                if (navigator.vibrate) navigator.vibrate(60);
                tapStartTime = 0; // evita tap-to-click dopo long press
            }
        }, LONG_PRESS_MS);
    }, { passive: false });

    pad.addEventListener('touchmove', (e) => {
        e.preventDefault();

        for (const t of e.touches) {
            const o = gestureOrigin[t.identifier];
            if (o) gestureMaxMove = Math.max(gestureMaxMove, Math.hypot(t.clientX - o.x, t.clientY - o.y));
        }

        if (e.touches.length === 2) {
            const midX = (e.touches[0].clientX + e.touches[1].clientX) / 2;
            const midY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
            const d = scrollDelta(midX - twoFingerLastX, midY - twoFingerLastY);
            twoFingerScrollAcc += d.v;
            twoFingerScrollAccX += d.h;
            twoFingerLastX = midX;
            twoFingerLastY = midY;
            scheduleSend();
            return;
        }

        if (!touchActive) return;
        const cx = e.touches[0].clientX, cy = e.touches[0].clientY;

        if (Math.abs(cx - tapStartX) > TAP_MAX_MOVE || Math.abs(cy - tapStartY) > TAP_MAX_MOVE) {
            tapMoved = true;
            clearTimeout(longPressTimer);
            if (dragCandidate && !tapDragging) {
                // Pulsante giù prima dei movimenti: i messaggi viaggiano in ordine.
                tapDragging = true;
                sendDrag('down');
            }
        }

        moveX += (cx - lastX); moveY += (cy - lastY);
        isMoving = true; lastX = cx; lastY = cy;
        scheduleSend();
    }, { passive: false });

    pad.addEventListener('touchend', (e) => {
        touchActive = false;
        clearTimeout(longPressTimer);
        if (e.touches.length > 0) return;   // restano dita giù: il gesto non è finito

        if (tapDragging) {
            endTapDrag();
            lastTapEnd = 0;
            tapStartTime = 0;
            resetGesture();
            return;
        }

        const now = Date.now();
        if (gestureMaxTouches >= 2) {
            const btn = multiTapButton(gestureMaxTouches, now - gestureStart, gestureMaxMove);
            if (btn) {
                sendClick(btn);
                if (navigator.vibrate) navigator.vibrate(30);
            }
            lastTapEnd = 0;
            tapStartTime = 0;
            resetGesture();
            return;
        }

        if (now - tapStartTime < TAP_MAX_MS && !tapMoved && tapStartTime > 0) {
            // Tap rapido = click sinistro (il doppio tap produce due click = double-click OS)
            sendClick('left');
            lastTapEnd = now; lastTapX = tapStartX; lastTapY = tapStartY;
        } else {
            lastTapEnd = 0;
        }
        tapStartTime = 0;
        resetGesture();
    }, { passive: false });

    pad.addEventListener('touchcancel', () => {
        touchActive = false;
        clearTimeout(longPressTimer);
        endTapDrag();               // un trascinamento interrotto non deve restare premuto
        tapStartTime = 0;
        lastTapEnd = 0;
        resetGesture();
    }, { passive: false });

    // --- CLICK ---
    const sendClick = (btn) => {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'click', btn: btn }));
    };
    // Pulsante sinistro giù/su per il tap-e-trascina (stesso messaggio del blocco
    // "trascina" del menu: il server rilascia comunque alla disconnessione).
    const sendDrag = (state) => {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'drag', state: state }));
    };

    // --- MENU E LOCKS ---
    const btnMenu = document.getElementById('btn-menu');
    const menuOverlay = document.getElementById('menu-overlay');

    // Stati Tasti Lock
    let locks = { drag: false, ctrl: false, shift: false };

    function resetLocks() {
        locks = { drag: false, ctrl: false, shift: false };
        // Anche il bottone del menu: con trascina attivo resta ambra, e dopo
        // una disconnessione segnalava un trascinamento che il server ha già
        // rilasciato.
        btnMenu.classList.remove('lock-active');
        updateLockUI('btn-drag', false);
        updateLockUI('btn-ctrl', false);
        updateLockUI('btn-shift', false);
    }

    function toggleLock(key, btnId) {
        locks[key] = !locks[key];
        const isActive = locks[key];
        updateLockUI(btnId, isActive);

        if (navigator.vibrate) navigator.vibrate(50);

        if (ws && ws.readyState === WebSocket.OPEN) {
            if (key === 'drag') {
                ws.send(JSON.stringify({ type: 'drag', state: isActive ? 'down' : 'up' }));
                // Feedback visivo sul bottone menu principale se drag è attivo
                if (isActive) btnMenu.classList.add('lock-active'); else btnMenu.classList.remove('lock-active');
            } else {
                ws.send(JSON.stringify({ type: 'key_toggle', key: key, state: isActive ? 'down' : 'up' }));
            }
        }
        // Meglio chiudere sempre per pulizia, l'utente vede lo stato dal bottone.
        closeMenu();
    }

    function updateLockUI(id, active) {
        const el = document.getElementById(id);
        if (active) el.classList.add('lock-active'); else el.classList.remove('lock-active');
    }

    // Con Motion l'opacità del velo è inline e la classe .visible decide solo
    // se riceve i tocchi: così si chiude subito al tatto ma sfuma a vista.
    function openMenu() {
        if (menuOverlay.classList.contains('visible')) return;
        menuOverlay.classList.add('visible');
        if (!anima(menuOverlay, { opacity: [0, 1] }, RAPIDA)) { pulisciStile(menuOverlay); return; }
        anima(menuOverlay.querySelectorAll('.menu-btn-item'),
              { opacity: [0, 1], scale: [0.92, 1], y: [10, 0] },
              { ...MOLLA, delay: MotionLib.stagger(0.018) });
        anima(menuOverlay.querySelector('.sens-box'), { opacity: [0, 1], y: [8, 0] },
              { ...MOLLA, delay: 0.12 });
    }
    function closeMenu() {
        if (!menuOverlay.classList.contains('visible')) return;
        menuOverlay.classList.remove('visible');
        if (!anima(menuOverlay, { opacity: 0 }, { duration: 0.14, ease: 'easeIn' })) pulisciStile(menuOverlay);
    }
    btnMenu.addEventListener('click', openMenu);
    menuOverlay.addEventListener('click', (e) => {
        if (e.target === menuOverlay) closeMenu();
    });

    // Helper: registra touchend (no 300ms delay iOS) con fallback click per mouse/desktop.
    // e.preventDefault() su touchend impedisce il click sintetico successivo.
    function addMenuTap(id, handler) {
        const el = document.getElementById(id);
        let moved = false;
        el.addEventListener('touchstart', () => { moved = false; }, { passive: true });
        el.addEventListener('touchmove',  () => { moved = true;  }, { passive: true });
        el.addEventListener('touchend', (e) => {
            if (!moved) { e.preventDefault(); handler(); }
        });
        el.addEventListener('click', handler); // fallback desktop/mouse
    }

    const send = (msg) => {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
    };

    // Gestione Bottoni Menu
    addMenuTap('btn-drag',  () => toggleLock('drag',  'btn-drag'));
    addMenuTap('btn-ctrl',  () => toggleLock('ctrl',  'btn-ctrl'));
    addMenuTap('btn-shift', () => toggleLock('shift', 'btn-shift'));

    addMenuTap('btn-esc', () => {
        send({ type: 'key', key: 'esc' });
        updateTextDisplay('esc'); closeMenu();
    });

    addMenuTap('btn-copy', () => {
        send({ type: 'hotkey', keys: ['ctrl', 'c'] });
        updateTextDisplay('copia'); closeMenu();
    });

    addMenuTap('btn-paste', () => {
        send({ type: 'hotkey', keys: ['ctrl', 'v'] });
        updateTextDisplay('incolla'); closeMenu();
    });

    addMenuTap('btn-select-all', () => {
        send({ type: 'hotkey', keys: ['ctrl', 'a'] });
        updateTextDisplay('seleziona tutto'); closeMenu();
    });

    addMenuTap('btn-win', () => {
        send({ type: 'key', key: 'win' });
        updateTextDisplay('win'); closeMenu();
    });

    addMenuTap('btn-media-play', () => {
        send({ type: 'key', key: 'media_play_pause' });
        closeMenu();
    });

    addMenuTap('btn-winv', () => {
        send({ type: 'hotkey', keys: ['win', 'v'] });
        updateTextDisplay('win+v'); closeMenu();
    });

    // --- SLIDER SENSIBILITA' ---
    const sensSlider = document.getElementById('sensitivity-slider');
    const sensValue  = document.getElementById('sens-value');
    sensSlider.value = sensitivity;
    sensValue.textContent = sensitivity.toFixed(1) + 'x';
    sensSlider.addEventListener('input', () => {
        sensitivity = parseFloat(sensSlider.value);
        sensValue.textContent = sensitivity.toFixed(1) + 'x';
        localStorage.setItem('lm_sensitivity', sensitivity);
    });

    // --- DISPLAY TESTO & TASTIERA ---
    const textDisplay = document.getElementById('text-display');
    let displayedText = ''; let displayTimeout;
    let previousValue = '';

    let testoUscita = null;   // animazione di chiusura in corso, interrompibile

    function updateTextDisplay(char) {
        displayedText = (char.length > 1) ? char : (char === '⌫' ? displayedText.slice(0, -1) : (char === '↵' ? displayedText + '\n' : displayedText + char));
        textDisplay.textContent = displayedText;
        // Un carattere che arriva mentre il pannello sfuma lo riporta su
        // senza farlo rientrare da capo.
        const entra = !textDisplay.classList.contains('active');
        if (testoUscita) { testoUscita.stop(); testoUscita = null; pulisciStile(textDisplay); }
        textDisplay.classList.add('active');
        if (entra && !anima(textDisplay, { opacity: [0, 1], y: [-8, 0] }, MOLLA)) pulisciStile(textDisplay);
        clearTimeout(displayTimeout);
        displayTimeout = setTimeout(nascondiTesto, 3000);
    }
    function nascondiTesto() {
        const chiudi = () => {
            testoUscita = null;
            textDisplay.classList.remove('active');
            pulisciStile(textDisplay);
            displayedText = '';
        };
        const a = anima(textDisplay, { opacity: 0, y: -6 }, { duration: 0.16, ease: 'easeIn' });
        if (!a) { chiudi(); return; }
        testoUscita = a;
        a.then(() => { if (testoUscita === a) chiudi(); });
    }

    addMenuTap('btn-keyboard', () => {
        hiddenInput.value = '';
        previousValue = ''; // Reset essenziale: evita ghost input al riavvio della tastiera
        hiddenInput.focus();
        closeMenu();
    });
    hiddenInput.addEventListener('input', (e) => {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        const val = hiddenInput.value;
        const { del, add } = diffTastiera(previousValue, val);
        if (del > 0) {
            // Un solo messaggio con il conteggio, non uno per carattere.
            // Prima il server scartava tutti i backspace successivi al
            // primo per via del debounce anti-autorepeat da 80ms: cancellare
            // cinque caratteri ne cancellava uno solo.
            ws.send(JSON.stringify({ type: 'key', key: 'backspace', count: del }));
            updateTextDisplay('⌫'.repeat(Math.min(del, 8)));
        }
        if (add) {
            ws.send(JSON.stringify({ type: 'text', char: add })); updateTextDisplay(add);
        }
        previousValue = val;
    });

    hiddenInput.addEventListener('keydown', (e) => {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        if (e.key === 'Enter') {
            e.preventDefault(); ws.send(JSON.stringify({ type: 'key', key: 'enter' }));
            updateTextDisplay('↵'); previousValue = ''; hiddenInput.value = '';
        } else if (e.key === 'Backspace') {
            if (hiddenInput.value.length === 0) {
                // Campo vuoto: 'input' non scatta, invia backspace manualmente
                ws.send(JSON.stringify({ type: 'key', key: 'backspace' })); updateTextDisplay('⌫');
            }
            // Campo non vuoto: l'evento 'input' gestisce la cancellazione
        }
    });

    // --- EFFETTI TOUCH UI ---
    ['btn-menu', 'touchpad'].forEach(id => {
        const el = document.getElementById(id);
        el.addEventListener('touchstart', () => el.classList.add('fluid-pressed'), { passive: true });
        el.addEventListener('touchend', () => el.classList.remove('fluid-pressed'), { passive: true });
    });
    document.querySelectorAll('.menu-btn-item').forEach(el => {
        el.addEventListener('touchstart',  () => el.classList.add('fluid-pressed'),    { passive: true });
        el.addEventListener('touchend',    () => el.classList.remove('fluid-pressed'), { passive: true });
        el.addEventListener('touchcancel', () => el.classList.remove('fluid-pressed'), { passive: true });
    });
