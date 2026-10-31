(() => {
    const $ = s => document.querySelector(s), E = CompanionCalendar.escape;

    function rememberChat(id) {
        try {
            if (id) localStorage.setItem('companion.currentChat', JSON.stringify(id)); else localStorage.removeItem('companion.currentChat');
        } catch {
        }
    }

    function rememberedChat() {
        try {
            const id = JSON.parse(localStorage.getItem('companion.currentChat'));
            return typeof id === 'string' && /^[a-f0-9]{32}$/.test(id) ? id : null;
        } catch {
            return null;
        }
    }

    let selected = null, records = [], messages = [], before = null, source = null, activeRun = null, revision = 0,
        pending = null, loading = false, sending = false;
    const labels = {
        pending: 'Ожидание',
        running: 'Пишет ответ…',
        completed: 'Завершено',
        cancelled: 'Остановлено',
        failed: 'Ошибка',
        interrupted: 'Прервано'
    };

    async function api(path, method = 'GET', body) {
        const response = await fetch('/api/' + path, {
            method,
            cache: 'no-store',
            headers: {'Content-Type': 'application/json'},
            body: body === undefined ? undefined : JSON.stringify(body)
        });
        const data = response.status === 204 ? null : await response.json();
        if (!response.ok) {
            const error = new Error(typeof data?.detail === 'string' ? data.detail : data?.detail?.message || 'Проверьте настройки и повторите попытку.');
            error.status = response.status;
            throw error;
        }
        return data;
    }

    function report(error) {
        $('#chat-error').textContent = error.message;
        $('#chat-error').hidden = false;
    }

    function clearError() {
        $('#chat-error').hidden = true;
    }

    const toolStates = {
        waiting_approval: 'Ожидает подтверждения',
        approved: 'Подтверждён',
        running: 'Выполняется',
        completed: 'Выполнен',
        denied: 'Отклонён',
        failed: 'Ошибка',
        unknown: 'Результат неизвестен — проверьте данные',
        cancelled: 'Отменён',
        interrupted: 'Прерван'
    };

    function createToolCard(tool) {
        const card = document.createElement('details');
        card.className = 'chat-tool';
        card.open = tool.status === 'waiting_approval';
        const summary = document.createElement('summary');
        summary.textContent = (tool.server_id ? tool.server_id + ' · ' : '') + tool.tool_name + ' — ' + (toolStates[tool.status] || tool.status);
        card.append(summary);
        const argsLabel = document.createElement('b');
        argsLabel.className = 'chat-tool-label';
        argsLabel.textContent = 'Аргументы';
        card.append(argsLabel);
        const args = document.createElement('pre');
        args.textContent = JSON.stringify(tool.arguments ?? {}, null, 2);
        card.append(args);
        if (tool.result !== null && tool.result !== undefined) {
            const resultLabel = document.createElement('b');
            resultLabel.className = 'chat-tool-label';
            resultLabel.textContent = 'Результат';
            card.append(resultLabel);
            const result = document.createElement('pre');
            result.textContent = typeof tool.result === 'string' ? tool.result : JSON.stringify(tool.result, null, 2);
            card.append(result);
        }
        if (tool.status === 'waiting_approval' && ['pending', 'running'].includes(tool.run_status)) {
            const actions = document.createElement('div');
            actions.className = 'chat-tool-actions';
            for (const [text, approve] of [['Разрешить', true], ['Отклонить', false]]) {
                const button = document.createElement('button');
                button.className = 'button' + (approve ? ' primary' : '');
                button.textContent = text;
                button.onclick = async () => {
                    actions.querySelectorAll('button').forEach(b => b.disabled = true);
                    try {
                        await api('chats/runs/' + tool.run_id + '/tools/' + tool.id + '/decision', 'POST', {approve});
                    } catch (error) {
                        report(error);
                        actions.querySelectorAll('button').forEach(b => b.disabled = false)
                    }
                };
                actions.append(button);
            }
            card.append(actions);
        }
        return card;
    }

    function renderTools(data) {
        const message = messages.find(m => m.id === data.assistant_message_id);
        if (message) message.tool_executions = (data.tools || []).map(tool => ({...tool, run_status: data.status}));
    }

    function renderList() {
        $('#chat-list').replaceChildren();
        const groups = new Map([['today', {label: 'Сегодня', items: []}], ['yesterday', {
            label: 'Вчера',
            items: []
        }], ['week', {label: 'На этой неделе', items: []}], ['older', {label: 'Ранее', items: []}]]);
        const now = new Date(), today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);
        const monday = new Date(today);
        monday.setDate(monday.getDate() - (monday.getDay() + 6) % 7);
        for (const chat of records) {
            const stamp = new Date(chat.updated_at || chat.created_at),
                day = new Date(stamp.getFullYear(), stamp.getMonth(), stamp.getDate());
            const key = day >= today ? 'today' : day >= yesterday ? 'yesterday' : day >= monday ? 'week' : 'older';
            groups.get(key).items.push(chat);
        }
        for (const group of groups.values()) {
            if (!group.items.length) continue;
            const heading = document.createElement('h3');
            heading.className = 'chat-list-group';
            heading.textContent = group.label;
            $('#chat-list').append(heading);
            const section = document.createElement('div');
            section.className = 'chat-list-group-items';
            $('#chat-list').append(section);
            for (const c of group.items) {
                const b = document.createElement('button');
                b.className = 'chat-list-item' + (selected?.id === c.id ? ' active' : '');
                b.innerHTML = '<span class="chat-list-icon">' + CompanionIcons.icon('chat') + '</span><span class="chat-list-copy"><b>' + E(c.title) + '</b><small>' + E(c.model) + '</small></span>';
                b.onclick = () => open(c.id).catch(report);
                if (selected?.id === c.id) b.setAttribute('aria-current', 'true');
                section.append(b);
                const measure = () => {
                    const copy = b.querySelector('.chat-list-copy');
                    for (const el of copy.children) {
                        const distance = Math.max(0, el.scrollWidth - copy.clientWidth);
                        el.style.setProperty('--travel', -distance + 'px');
                        el.style.setProperty('--duration', Math.max(3, distance / 30) + 's');
                        el.classList.toggle('overflows', distance > 0)
                    }
                };
                b.addEventListener('pointerenter', measure);
                b.addEventListener('focus', measure);
            }
        }
    }

    async function load(more = false) {
        if (loading || CompanionAPI.preview) return;
        loading = true;
        const openingRevision = revision;
        try {
            const rows = await api('chats?offset=' + (more ? records.length : 0));
            records = more ? [...records, ...rows] : rows;
            renderList();
            $('#chat-more').hidden = rows.length < 50;
            const saved = rememberedChat();
            if (!more && !selected && saved && revision === openingRevision) {
                try {
                    await open(saved);
                } catch (e) {
                    if (e.status === 404) rememberChat(null); else throw e;
                }
            }
        } catch (e) {
            report(e)
        } finally {
            loading = false
        }
    }

    function markdown(text) {
        // Small, deliberately bounded Markdown subset. Escape HTML before inserting any markup.
        const chunks = text.split(/\x60\x60\x60/);
        return chunks.map((part, i) => {
            if (i % 2) return '<pre><code>' + highlight(part.replace(/^[a-zA-Z0-9_+-]*\n/, '')) + '</code></pre>';
            return blocks(part);
        }).join('');
    }

    function inline(text) {
        return text.split(/(\x60[^\x60\n]+\x60)/g).map((s, i) => i % 2 ? '<code>' + E(s.slice(1, -1)) + '</code>' : E(s)
            .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
            .replace(/__([^_\n]+)__/g, '<strong>$1</strong>')
            .replace(/\*([^*\n]+)\*/g, '<em>$1</em>')
            .replace(/(^|\s)_([^_\n]+)_(?=\s|[.,!?]|$)/g, '$1<em>$2</em>')
            .replace(/~~([^~\n]+)~~/g, '<del>$1</del>')).join('');
    }

    function blocks(text) {
        let html = '', list = null;
        const close = () => {
            if (list) {
                html += '</' + list + '>';
                list = null
            }
        };
        for (const line of text.split('\n')) {
            const item = line.match(/^\s*(?:([-+*])|\d+[.)])\s+(.+)$/);
            if (item) {
                const type = item[1] ? 'ul' : 'ol';
                if (list !== type) {
                    close();
                    list = type;
                    html += '<' + type + '>'
                }
                html += '<li>' + inline(item[2]) + '</li>';
                continue
            }
            close();
            const heading = line.match(/^(#{1,6})\s+(.+)$/);
            if (heading) {
                const level = heading[1].length;
                html += '<h' + level + '>' + inline(heading[2]) + '</h' + level + '>';
            } else if (/^\s*(---+|\*\*\*+|___+)\s*$/.test(line)) html += '<hr>';
            else if (/^>\s?/.test(line)) html += '<blockquote>' + inline(line.replace(/^>\s?/, '')) + '</blockquote>';
            else html += inline(line) + '<br>';
        }
        close();
        return html;
    }

    function resizeInput() {
        const input = $('#chat-input');
        if (!input.clientWidth) return;
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 150) + 'px';
        input.style.overflowY = input.scrollHeight > 150 ? 'auto' : 'hidden';
    }

    $('#chat-input').rows = 1;
    $('#chat-input').addEventListener('input', resizeInput);
    let inputWidth = 0;
    new ResizeObserver(entries => {
        const width = entries[0].contentRect.width;
        if (width !== inputWidth) {
            inputWidth = width;
            resizeInput()
        }
    }).observe($('#chat-input'));

    function highlight(text) {
        // Tokenize plain text first: no provider-supplied HTML or attributes are accepted.
        return text.split(/("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|\b(?:def|class|return|import|from|async|await|if|else|for|while|const|let|function|true|false|null|None|True|False)\b|\b\d+(?:\.\d+)?\b)/g).map((s, i) => {
            if (i % 2 === 0) return E(s);
            const kind = /^["']/.test(s) ? 'string' : /^\d/.test(s) ? 'number' : 'keyword';
            return '<span class="' + kind + '">' + E(s) + '</span>';
        }).join('');
    }

    function renderMessages() {
        const box = $('#chat-history'), near = box.scrollHeight - box.scrollTop - box.clientHeight < 90;
        const container = $('#chat-messages');
        container.replaceChildren();
        for (const message of messages) {
            const user = message.role === 'user', article = document.createElement('article');
            article.className = 'chat-message ' + (user ? 'user' : 'assistant');
            const avatar = document.createElement('span');
            avatar.className = 'chat-avatar';
            avatar.setAttribute('aria-hidden', 'true');
            avatar.innerHTML = CompanionIcons.icon(user ? 'user' : 'spark');
            const content = document.createElement('div');
            content.className = 'chat-message-content';
            const header = document.createElement('header'), author = document.createElement('b'),
                state = document.createElement('span');
            author.textContent = user ? 'Вы' : 'Folliant';
            state.textContent = message.status === 'completed' ? '' : labels[message.status] || message.status;
            header.append(author, state);
            const body = document.createElement('div');
            body.className = 'body';
            body.innerHTML = markdown(message.text || '');
            content.append(header, body);
            const executions = message.tool_executions || [];
            if (executions.length) {
                const group = document.createElement('div');
                group.className = 'chat-message-tools';
                executions.forEach(tool => group.append(createToolCard(tool)));
                content.append(group);
            }
            article.append(avatar, content);
            container.append(article);
        }
        $('#chat-older').hidden = before === null;
        if (near) box.scrollTop = box.scrollHeight;
    }

    let busyProvider = null, checkingAvailability = false;

    async function checkAvailability() {
        if (checkingAvailability || !selected || $('#chat-page').hidden || CompanionAPI.preview) return;
        checkingAvailability = true;
        const id = selected.id;
        try {
            const rows = await api('chats/provider-availability');
            if (selected?.id !== id) return;
            busyProvider = rows.find(row => row.provider_id === selected.provider_id && row.conversation_id !== id) || null;
            controls();
        } catch {
        } finally {
            checkingAvailability = false;
        }
    }

    setInterval(checkAvailability, 2000);

    function controls() {
        resizeInput();
        const running = !!activeRun || sending || !!busyProvider;
        $('#chat-input').disabled = !selected || running || !selected.provider_id;
        $('#chat-send').disabled = !selected || running || !selected.provider_id;
        $('#chat-stop').hidden = !activeRun;
        $('#chat-settings').disabled = !selected || running;
        $('#chat-mcp-open').disabled = !selected || running;
        updateMcpCount();
        let notice = $('#chat-provider-busy');
        if (!notice) {
            notice = document.createElement('p');
            notice.id = 'chat-provider-busy';
            notice.className = 'form-hint';
            $('#chat-compose').before(notice);
        }
        notice.hidden = !busyProvider;
        notice.textContent = busyProvider ? 'Провайдер занят в другом чате. Отправка станет доступна после завершения.' : '';
    }

    function updateMcpCount() {
        const count = selected?.mcp_servers?.length || 0;
        $('#chat-mcp-count').textContent = count + ' MCP';
    }

    async function editMcpConnections() {
        if (!selected || activeRun || sending || busyProvider) return;
        const dialog = $('#chat-mcp-dialog');
        const chatId = selected.id;
        const servers = await api('mcp/servers');
        const toolsByServer = await Promise.all(servers.map(s => api('mcp/servers/' + encodeURIComponent(s.id) + '/tools').catch(() => [])));
        if (!selected || selected.id !== chatId) return;
        const selectedIds = new Set(selected.mcp_servers || []);
        const sorted = servers.map((server, index) => ({server, tools: toolsByServer[index] || []}))
            .sort((a, b) => Number(b.server.is_internal) - Number(a.server.is_internal) || a.server.name.localeCompare(b.server.name, 'ru'));
        dialog.innerHTML = '<div class="chat-mcp-panel"><header><div><h2>Инструменты чата</h2><p>Выберите подключения, которыми помощник сможет пользоваться в этом разговоре.</p></div><span class="chat-mcp-badge"></span></header><div class="chat-mcp-rows"></div><p class="chat-mcp-note">Изменения данных через инструменты требуют вашего подтверждения.</p><div class="dialog-actions"><button class="button" type="button" data-dismiss>Отмена</button><button class="button primary" type="button" data-save>Сохранить</button></div></div>';
        const rows = dialog.querySelector('.chat-mcp-rows');
        if (!sorted.length) rows.innerHTML = '<p class="chat-mcp-empty">Нет доступных MCP-подключений. Добавьте их в настройках приложения.</p>';
        for (const {server, tools} of sorted) {
            const row = document.createElement('label');
            row.className = 'chat-mcp-row';
            const copy = document.createElement('span');
            copy.className = 'chat-mcp-row-copy';
            const name = document.createElement('b');
            name.textContent = server.name;
            const info = document.createElement('small');
            info.textContent = (server.is_internal ? 'Внутренний плагин · ' : '') + (tools.length ? tools.length + ' инструментов' : 'Подключение недоступно');
            copy.append(name, info);
            const check = document.createElement('input');
            check.type = 'checkbox';
            check.value = server.id;
            check.checked = selectedIds.has(server.id);
            row.append(copy, check);
            rows.append(row);
        }
        const badge = dialog.querySelector('.chat-mcp-badge');
        const refreshBadge = () => badge.textContent = rows.querySelectorAll('input:checked').length + ' активно';
        rows.addEventListener('change', refreshBadge);
        refreshBadge();
        dialog.querySelector('[data-dismiss]').onclick = () => dialog.close();
        dialog.querySelector('[data-save]').onclick = async event => {
            const button = event.currentTarget;
            button.disabled = true;
            try {
                const latest = await api('chats/' + chatId);
                const mcp_servers = [...rows.querySelectorAll('input:checked')].map(input => input.value);
                const payload = {
                    title: latest.title, provider_id: latest.provider_id, model: latest.model,
                    context_window_tokens: latest.context_window_tokens, max_output_tokens: latest.max_output_tokens,
                    system_prompt: latest.system_prompt, mcp_servers
                };
                const saved = await api('chats/' + chatId, 'PUT', payload);
                if (selected?.id === chatId) {
                    selected = saved;
                    updateMcpCount();
                }
                dialog.close();
            } catch (error) {
                report(error);
                button.disabled = false;
            }
        };
        dialog.showModal();
    }

    $('#chat-mcp-open').onclick = () => editMcpConnections().catch(report);

    function observe(run) {
        source?.close();
        activeRun = ['pending', 'running'].includes(run.status) ? run.id : null;
        controls();
        source = new EventSource('/api/chats/runs/' + run.id + '/events');
        const connection = source;

        function update(event) {
            if (source !== connection) return;
            const data = JSON.parse(event.data);
            let msg = messages.find(m => m.id === data.assistant_message_id);
            if (!msg) {
                msg = {id: data.assistant_message_id, role: 'assistant', position: data.position};
                messages.push(msg)
            }
            Object.assign(msg, {text: data.text, status: data.answer_complete ? 'completed' : data.status});
            const phases = {
                generating: 'Пишет ответ…',
                waiting_approval: 'Ожидает вашего решения',
                tool_running: 'Выполняет MCP-инструмент',
                summarizing: 'Сжимаю историю…'
            };
            $('#chat-status').textContent = (data.status === 'running' ? phases[data.phase] || labels[data.status] : labels[data.status]) + (data.error ? ' · ' + data.error : '');
            renderTools(data);
            renderMessages();
            if (!['pending', 'running'].includes(data.status)) {
                connection.close();
                activeRun = null;
                controls();
                load()
            }
        }

        ['snapshot', 'progress', 'completed'].forEach(name => connection.addEventListener(name, update));
        connection.onerror = () => {
            if (source === connection) $('#chat-status').textContent = 'Восстанавливаем связь с генерацией…'
        };
    }

    async function open(id) {
        const token = ++revision;
        source?.close();
        activeRun = null;
        clearError();
        const [c, history, run] = await Promise.all([api('chats/' + id), api('chats/' + id + '/messages'), api('chats/' + id + '/run')]);
        if (token !== revision) return;
        selected = c;
        busyProvider = null;
        checkAvailability();
        messages = history.items;
        before = history.next_before;
        pending = null;
        rememberChat(c.id);
        $('#chat-title').textContent = c.title;
        $('#chat-model').textContent = c.model + (c.provider_id ? '' : ' · подключение удалено');
        $('#chat-status').textContent = '';
        $('#chat-input').value = '';
        renderList();
        renderMessages();
        controls();
        $('#chat-history').scrollTop = $('#chat-history').scrollHeight;
        if (run) observe(run);
    }

    $('#chat-older').onclick = async () => {
        try {
            const id = selected.id;
            const data = await api('chats/' + id + '/messages?before=' + before);
            if (selected.id !== id) return;
            const box = $('#chat-history'), height = box.scrollHeight;
            messages = [...data.items, ...messages];
            before = data.next_before;
            renderMessages();
            box.scrollTop += box.scrollHeight - height
        } catch (e) {
            report(e)
        }
    };
    $('#chat-more').onclick = () => load(true);
    $('#chat-compose').onsubmit = async event => {
        event.preventDefault();
        if (!selected || activeRun || sending || busyProvider) return;
        const text = $('#chat-input').value;
        if (!text.trim()) return;
        if (!pending || pending.text !== text) pending = {text, request_id: crypto.randomUUID()};
        sending = true;
        controls();
        clearError();
        try {
            const id = selected.id;
            const run = await api('chats/' + id + '/messages', 'POST', pending);
            if (selected?.id === id) {
                await open(id);
                if (selected?.id === id) {
                    $('#chat-input').value = '';
                    pending = null;
                    observe(run)
                }
            }
        } catch (e) {
            report(e)
        } finally {
            sending = false;
            controls()
        }
    };
    $('#chat-stop').onclick = async () => {
        try {
            await api('chats/runs/' + activeRun + '/cancel', 'POST')
        } catch (e) {
            report(e)
        }
    };
    $('#chat-input').onkeydown = e => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            $('#chat-compose').requestSubmit()
        }
    };

    async function settings(c = null) {
        const dialog = $('#chat-dialog');
        const providers = await api('llm/providers');
        const v = c || {
            title: 'Новый разговор',
            provider_id: providers[0]?.id || '',
            model: '',
            context_window_tokens: 8192,
            max_output_tokens: 2048,
            system_prompt: ''
        };
        dialog.innerHTML = '<div class="dialog-body"><h2>' + (c ? 'Настройки разговора' : 'Новый разговор') + '</h2><form class="dialog-form"><label>Название<input name="title" maxlength="128" required value="' + E(v.title) + '"></label><label>Подключение<select name="provider_id" required><option value="">Выберите провайдера</option>' + providers.map(p => '<option value="' + E(p.id) + '"' + (p.id === v.provider_id ? ' selected' : '') + '>' + E(p.name) + '</option>').join('') + '</select></label><label>Модель<input name="model" list="chat-model-options" required maxlength="255" value="' + E(v.model) + '"><datalist id="chat-model-options"></datalist></label><button type="button" class="text-button" id="chat-discover">Обновить список моделей</button><p id="chat-model-hint" class="form-hint">Если сервер недоступен, имя модели можно ввести вручную.</p><div class="form-row"><label>Контекстное окно<input type="number" name="context_window_tokens" min="1024" max="2000000" required value="' + v.context_window_tokens + '"></label><label>Максимум токенов ответа<input type="number" name="max_output_tokens" min="1" max="1000000" required value="' + v.max_output_tokens + '"></label></div><div class="chat-budget">Бюджет входного контекста<br><strong id="chat-budget"></strong><p class="form-hint">С учётом резерва 256 токенов. Старые обмены исключаются из отправляемого контекста, история сохраняется.</p></div><label>Контекст этого разговора<textarea name="system_prompt" rows="4" maxlength="100000" placeholder="О чём помощнику следует помнить?">' + E(v.system_prompt) + '</textarea></label><p class="form-hint">Дополняет общие инструкции Folliant. Лимит должен соответствовать настройкам запущенного сервера.</p><p class="form-error" id="chat-form-error" hidden></p><div class="dialog-actions">' + (c ? '<button type="button" class="button danger" id="chat-delete">Удалить</button>' : '') + '<button type="button" class="button" id="chat-dismiss">Отмена</button><button type="submit" class="button primary">Сохранить</button></div></form></div>';
        dialog.showModal();
        const form = dialog.querySelector('form'), f = form.elements;
        let version = 0, busy = false;
        const hint = $('#chat-model-hint');
        const budget = () => $('#chat-budget').textContent = Math.max(0, +f.context_window_tokens.value - +f.max_output_tokens.value - 256).toLocaleString('ru-RU') + ' токенов';
        f.context_window_tokens.oninput = f.max_output_tokens.oninput = budget;
        budget();

        async function discover() {
            const stamp = ++version;
            const provider = f.provider_id.value;
            if (!provider) return;
            hint.textContent = 'Загружаем модели…';
            try {
                const models = await api('llm/providers/' + encodeURIComponent(provider) + '/models');
                if (stamp !== version || !dialog.open) return;
                $('#chat-model-options').innerHTML = models.map(m => '<option value="' + E(m.id) + '"></option>').join('');
                hint.textContent = 'Доступно моделей: ' + models.length + '. Выберите из списка или введите имя.'
            } catch (e) {
                if (stamp === version) hint.textContent = 'Список недоступен. Укажите имя модели вручную.'
            }
        }

        f.provider_id.onchange = () => {
            f.model.value = '';
            $('#chat-model-options').replaceChildren();
            discover()
        };
        $('#chat-discover').onclick = discover;
        f.model.onchange = async () => {
            const provider = f.provider_id.value, model = f.model.value;
            try {
                const info = await api('llm/providers/' + encodeURIComponent(provider) + '/model-info?model=' + encodeURIComponent(model));
                if (f.provider_id.value !== provider || f.model.value !== model || !dialog.open) return;
                hint.textContent = info.context_window_tokens ? 'Паспортный предел: ' + info.context_window_tokens + ' токенов. На сервере может быть задан меньший лимит.' : 'API не сообщил размер контекста. Укажите лимит вручную.'
            } catch {
                hint.textContent = 'Не удалось получить предел контекста. Укажите его вручную.'
            }
        };
        $('#chat-dismiss').onclick = () => dialog.close();
        dialog.oncancel = e => {
            if (busy) e.preventDefault()
        };
        const fail = e => {
            $('#chat-form-error').textContent = e.message;
            $('#chat-form-error').hidden = false
        };

        async function action(fn) {
            if (busy) return;
            busy = true;
            const buttons = [...form.querySelectorAll('button')];
            buttons.forEach(b => b.disabled = true);
            try {
                await fn()
            } catch (e) {
                fail(e)
            } finally {
                busy = false;
                buttons.forEach(b => b.disabled = false)
            }
        }

        form.onsubmit = e => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(form));
            data.mcp_servers = v.mcp_servers || [];
            data.context_window_tokens = +data.context_window_tokens;
            data.max_output_tokens = +data.max_output_tokens;
            action(async () => {
                const result = await api('chats' + (c ? '/' + c.id : ''), c ? 'PUT' : 'POST', data);
                dialog.close();
                await load();
                await open(result.id)
            })
        };
        if (c) $('#chat-delete').onclick = () => {
            if (confirm('Удалить разговор и всю его историю?')) action(async () => {
                await api('chats/' + c.id, 'DELETE');
                rememberChat(null);
                dialog.close();
                source?.close();
                selected = null;
                activeRun = null;
                messages = [];
                $('#chat-title').textContent = 'Ваш собеседник';
                $('#chat-model').textContent = '';
                $('#chat-status').textContent = '';
                renderMessages();
                controls();
                await load()
            })
        };
        discover();
    }

    $('#chat-new').onclick = () => settings().catch(report);
    $('#chat-settings').onclick = () => settings(selected).catch(report);
    window.CompanionChat = {load};
    if (!$('#chat-page').hidden) load();
})();

