// Liquid Mouse — client, 4/4: file manager (SFTP).
//
// Parte del client diviso in quattro script (vedi app-core.js).

    // --- FILE MANAGER (SFTP) ---------------------------------------------------
    // Il telefono non parla SSH: chiede al PC (messaggi sftp_*, vedi
    // liquidmouse/net/protocol.py) e trasferisce i file via HTTP con un
    // biglietto monouso (/sftp/dl, /sftp/up). I nomi dei file sono dati
    // esterni: si scrivono sempre con textContent, mai innerHTML.

    // --- FILE: contratto (estratto ed eseguito da tests con node) ---
    function formatSize(n) {
        if (!(n >= 0)) return '';
        const unita = ['B', 'KB', 'MB', 'GB', 'TB'];
        let i = 0;
        while (n >= 1024 && i < unita.length - 1) { n /= 1024; i++; }
        return (i === 0 || n >= 10 ? Math.round(n) : n.toFixed(1)) + ' ' + unita[i];
    }
    function joinPath(folder, name) {
        return (folder === '/' ? '' : folder.replace(/\/+$/, '')) + '/' + name;
    }
    function parentPath(path) {
        const i = path.replace(/\/+$/, '').lastIndexOf('/');
        return i <= 0 ? '/' : path.slice(0, i);
    }
    // --- fine contratto ---

    const filesEl = {
        banner: document.getElementById('files-banner'),
        profiles: document.getElementById('files-profiles'),
        profileList: document.getElementById('files-profile-list'),
        browser: document.getElementById('files-browser'),
        path: document.getElementById('files-path'),
        list: document.getElementById('files-list'),
        progress: document.getElementById('files-progress'),
        input: document.getElementById('files-input'),
    };
    let filesPath = '/';
    let filesConnected = false;
    let uploadQueue = [];
    let uploadBusy = false;
    let uploadDone = false;   // almeno un file è stato caricato: ricarica l'elenco alla fine

    function filesSend(msg) {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
    }
    function filesError(text) {
        filesEl.banner.textContent = text;
        mostraBanner(filesEl.banner);
        clearTimeout(filesError.t);
        filesError.t = setTimeout(() => filesEl.banner.classList.remove('visible'), 6000);
    }
    function filesShow(browser) {
        const cambia = filesEl.browser.classList.contains('visible') !== browser;
        filesEl.browser.classList.toggle('visible', browser);
        filesEl.profiles.style.display = browser ? 'none' : '';
        if (cambia) anima(browser ? filesEl.browser : filesEl.profiles, { opacity: [0, 1] }, RAPIDA);
    }
    function filesReset() {
        filesConnected = false;
        uploadQueue = []; uploadBusy = false;
        filesEl.progress.textContent = '';
        filesShow(false);
    }
    function onFilesTabOpen() {
        if (!filesConnected) filesSend({ type: 'sftp_profiles' });
    }
    function filesList(path) { filesSend({ type: 'sftp_list', path: path }); }

    // Bottone con conferma al secondo tocco, come la × delle sessioni.
    function confirmButton(label, action) {
        const b = document.createElement('button');
        b.className = 'session-card-close';
        b.textContent = label;
        let timer = null;
        b.addEventListener('click', (e) => {
            e.stopPropagation();
            if (b.classList.contains('confirm')) {
                clearTimeout(timer);
                const riga = b.closest('.session-card');
                if (riga) anima(riga, { opacity: 0.45 }, RAPIDA);
                action();
                return;
            }
            b.classList.add('confirm');
            b.textContent = 'sicuro?';
            anima(b, { scale: [0.88, 1] }, MOLLA);
            timer = setTimeout(() => { b.classList.remove('confirm'); b.textContent = label; }, 3000);
        });
        return b;
    }

    function renderProfiles(profiles) {
        filesEl.profileList.replaceChildren();
        document.getElementById('files-profile-count').textContent =
            contaAttive(profiles.length, 'salvato', 'salvati');
        profiles.forEach(p => {
            const card = document.createElement('div');
            card.className = 'session-card existing';
            const label = document.createElement('div');
            label.className = 'session-card-label';
            const name = document.createElement('div');
            name.className = 'name'; name.textContent = p.name;
            const meta = document.createElement('div');
            meta.className = 'meta';
            meta.textContent = `${p.user}@${p.host}:${p.port}`;
            label.append(name, meta);
            const actions = document.createElement('div');
            actions.className = 'session-card-actions';
            const go = document.createElement('button');
            go.className = 'session-card-btn btn-resume';
            go.textContent = 'apri';
            go.addEventListener('click', () => {
                go.disabled = true; go.textContent = '...';
                filesSend({ type: 'sftp_connect', name: p.name });
            });
            actions.append(go, confirmButton('×', () =>
                filesSend({ type: 'sftp_profile_delete', name: p.name })));
            card.append(label, actions);
            filesEl.profileList.append(card);
        });
        animaElenco(filesEl.profileList);
    }

    // Icona a tratto come quelle del menu (stroke="currentColor"): il glifo ✎
    // non esiste in Space Mono e il telefono lo pescava da un font emoji.
    function iconaSvg(d) {
        const ns = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('viewBox', '0 0 24 24');
        svg.setAttribute('fill', 'none');
        svg.setAttribute('stroke', 'currentColor');
        svg.setAttribute('stroke-width', '2');
        svg.setAttribute('stroke-linecap', 'round');
        svg.setAttribute('stroke-linejoin', 'round');
        svg.setAttribute('aria-hidden', 'true');
        const path = document.createElementNS(ns, 'path');
        path.setAttribute('d', d);
        svg.append(path);
        return svg;
    }
    const ICONA_MATITA = 'M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z';

    function fmtDate(t) {
        if (!t) return '';
        const d = new Date(t * 1000);
        const p = (n) => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
    }

    function renderListing(msg) {
        filesPath = msg.path;
        filesEl.path.textContent = msg.path;
        filesEl.list.replaceChildren();
        if (!msg.entries.length) {
            const e = document.createElement('div');
            e.className = 'file-empty'; e.textContent = 'cartella vuota';
            filesEl.list.append(e);
        }
        msg.entries.forEach(f => {
            const row = document.createElement('div');
            row.className = 'session-card file-row' + (f.dir ? ' is-dir' : '');
            const label = document.createElement('div');
            label.className = 'session-card-label';
            const name = document.createElement('div');
            name.className = 'name';
            if (f.dir) {
                const mark = document.createElement('span');
                mark.className = 'dir-mark';
                mark.setAttribute('aria-hidden', 'true');
                mark.textContent = '▸';
                name.append(mark);
            }
            name.append(f.name);
            const meta = document.createElement('div');
            meta.className = 'meta';
            meta.textContent = [f.dir ? 'cartella' : formatSize(f.size), fmtDate(f.mtime)]
                .filter(Boolean).join(' // ');
            label.append(name, meta);
            row.addEventListener('click', () => {
                if (f.dir) filesList(joinPath(filesPath, f.name));
                else filesSend({ type: 'sftp_ticket', direction: 'dl', path: filesPath, name: f.name });
            });
            const actions = document.createElement('div');
            actions.className = 'session-card-actions';
            const ren = document.createElement('button');
            ren.className = 'session-card-close';
            ren.append(iconaSvg(ICONA_MATITA));
            ren.setAttribute('aria-label', `rinomina ${f.name}`);
            ren.addEventListener('click', (e) => {
                e.stopPropagation();
                const nuovo = prompt('nuovo nome', f.name);
                if (nuovo && nuovo !== f.name)
                    filesSend({ type: 'sftp_rename', path: filesPath, old: f.name, new: nuovo });
            });
            actions.append(ren, confirmButton('×', () =>
                filesSend({ type: 'sftp_delete', path: filesPath, name: f.name, dir: f.dir })));
            row.append(label, actions);
            filesEl.list.append(row);
        });
        if (msg.truncated) {
            const e = document.createElement('div');
            e.className = 'file-empty'; e.textContent = 'elenco troncato';
            filesEl.list.append(e);
        }
        filesEl.list.scrollTop = 0;
        animaElenco(filesEl.list);
    }

    function startDownload(msg) {
        const a = document.createElement('a');
        a.href = '/sftp/dl?t=' + encodeURIComponent(msg.token);
        a.download = msg.name;
        document.body.append(a);
        a.click();
        a.remove();
    }

    // Upload in coda, un file alla volta: ogni file ha il suo biglietto.
    function queueUploads(files) {
        uploadQueue.push(...files);
        if (!uploadBusy) nextUpload();
    }
    function nextUpload(overwrite) {
        const file = uploadQueue[0];
        if (!file) {
            uploadBusy = false;
            filesEl.progress.textContent = '';
            if (uploadDone) { uploadDone = false; filesList(filesPath); }
            return;
        }
        uploadBusy = true;
        filesEl.progress.style.setProperty('--p', '0%');
        filesEl.progress.textContent = `carico ${file.name}...`;
        filesSend({ type: 'sftp_ticket', direction: 'up', path: filesPath,
                    name: file.name, overwrite: overwrite === true });
    }
    function sendUpload(msg) {
        const file = uploadQueue[0];
        if (!file) return;
        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/sftp/up?t=' + encodeURIComponent(msg.token));
        xhr.upload.onprogress = (e) => {
            if (!e.lengthComputable) return;
            const pct = Math.round(100 * e.loaded / e.total);
            filesEl.progress.textContent = `carico ${file.name} // ${pct}%`;
            filesEl.progress.style.setProperty('--p', `${pct}%`);
        };
        xhr.onload = () => {
            if (xhr.status === 200) uploadDone = true;
            else filesError(`upload di ${file.name} non riuscito`);
            uploadQueue.shift(); nextUpload();
        };
        xhr.onerror = () => {
            filesError(`upload di ${file.name} interrotto`);
            uploadQueue.shift(); nextUpload();
        };
        xhr.send(file);
    }

    function handleFilesMessage(msg) {
        if (msg.type === 'sftp_profiles') {
            renderProfiles(msg.profiles);
        } else if (msg.type === 'sftp_connected') {
            filesConnected = true;
            filesShow(true);
            filesList(msg.path);
        } else if (msg.type === 'sftp_disconnected') {
            filesReset();
            filesSend({ type: 'sftp_profiles' });
        } else if (msg.type === 'sftp_listing') {
            renderListing(msg);
        } else if (msg.type === 'sftp_ok') {
            filesList(filesPath);
        } else if (msg.type === 'sftp_ticket') {
            if (msg.direction === 'dl') startDownload(msg); else sendUpload(msg);
        } else if (msg.type === 'sftp_error') {
            // Un upload in corso che trova il file già presente chiede conferma;
            // qualunque altro errore lo interrompe e passa al file dopo.
            if (uploadBusy && msg.code === 'exists') {
                if (confirm(`${uploadQueue[0].name} esiste già. sovrascrivere?`)) { nextUpload(true); return; }
                uploadQueue.shift(); nextUpload(); return;
            }
            if (uploadBusy && (msg.code === 'remote_upload' || msg.code === 'disconnected')) {
                uploadQueue = []; uploadBusy = false; filesEl.progress.textContent = '';
            } else if (uploadBusy) {
                uploadQueue.shift(); nextUpload();
            }
            filesError(msg.msg);
            // Un connect fallito lascia il bottone "apri" bloccato: si ridisegna.
            if (!filesConnected) filesSend({ type: 'sftp_profiles' });
        }
    }

    document.getElementById('files-profile-form').addEventListener('submit', (e) => {
        e.preventDefault();
        const v = (id) => document.getElementById(id).value.trim();
        filesSend({ type: 'sftp_profile_save', name: v('pf-name'), host: v('pf-host'),
                    port: parseInt(v('pf-port'), 10) || 22, user: v('pf-user'),
                    password: document.getElementById('pf-pass').value });
        document.getElementById('pf-pass').value = '';
    });
    document.getElementById('files-back').addEventListener('click', () => {
        filesSend({ type: 'sftp_disconnect' });
    });
    document.getElementById('files-up').addEventListener('click', () => filesList(parentPath(filesPath)));
    document.getElementById('files-refresh').addEventListener('click', () => filesList(filesPath));
    document.getElementById('files-mkdir').addEventListener('click', () => {
        const nome = prompt('nome della nuova cartella');
        if (nome) filesSend({ type: 'sftp_mkdir', path: filesPath, name: nome });
    });
    document.getElementById('files-upload').addEventListener('click', () => filesEl.input.click());
    filesEl.input.addEventListener('change', () => {
        queueUploads(Array.from(filesEl.input.files));
        filesEl.input.value = '';
    });
