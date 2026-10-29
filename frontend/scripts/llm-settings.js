(() => {
    const A = CompanionLLMAPI, E = CompanionCalendar.escape, I = CompanionIcons.icon;
    const list = document.querySelector('#llm-list'), state = document.querySelector('#llm-state');
    const error = document.querySelector('#llm-error'), reload = document.querySelector('#llm-reload');
    const add = document.querySelector('#llm-add'), dialog = document.querySelector('#llm-dialog');
    const content = document.querySelector('#llm-dialog-content');
    let generation = 0, revision = 0, busy = false, focus = null;

    async function load() {
        const token = ++generation;
        error.hidden = true;
        reload.disabled = true;
        list.setAttribute('aria-busy', 'true');
        state.textContent = 'Загружаем подключения…';
        try {
            const records = await A.list();
            if (token !== generation) return;
            records.sort((a, b) => a.name.localeCompare(b.name, 'ru'));
            list.replaceChildren();
            state.textContent = A.preview ? 'Пример списка · предпросмотр' : 'Выберите провайдера, чтобы открыть настройки';
            for (const record of records) {
                const row = document.createElement('button');
                row.type = 'button';
                row.className = 'plugin-row llm-row';
                row.innerHTML = '<span class="plugin-emblem">' + I(record.kind === 'ollama' ? 'spark' : 'book') + '</span>' +
                    '<span class="plugin-copy"><span class="plugin-name"><strong>' + E(record.name) + '</strong><span class="plugin-tag">' + E(record.kind === 'ollama' ? 'Ollama' : 'OpenAI') + '</span></span>' +
                    '<small>' + E(record.base_url) + '</small></span>' + (record.has_api_key ? '<span class="llm-key-state">Ключ сохранён</span>' : '') + I('chevron-right');
                row.onclick = () => edit(record.id);
                list.append(row);
            }
            if (!records.length) list.innerHTML = '<p class="plugin-empty">Подключений пока нет.<br>Добавьте OpenAI или Ollama кнопкой выше.</p>';
        } catch (e) {
            if (token !== generation) return;
            state.textContent = 'Не удалось обновить список';
            error.textContent = e.message;
            error.hidden = false;
        } finally {
            if (token === generation) {
                reload.disabled = false;
                list.setAttribute('aria-busy', 'false');
            }
        }
    }

    function shell(title, body) {
        revision++;
        if (!dialog.open) focus = document.activeElement;
        content.innerHTML = '<div class="dialog-body"><div class="dialog-top"><div><div class="dialog-category">' + I('spark') + 'ПОДКЛЮЧЕНИЯ К МОДЕЛЯМ</div><h2 id="llm-dialog-title">' + E(title) + '</h2></div><button type="button" class="icon-button" data-close aria-label="Закрыть">' + I('close') + '</button></div>' + body + '</div>';
        content.querySelector('[data-close]').onclick = () => {
            if (!busy) dialog.close();
        };
        if (!dialog.open) dialog.showModal();
    }

    dialog.addEventListener('cancel', event => {
        if (busy) event.preventDefault();
    });
    dialog.addEventListener('close', () => {
        revision++;
        if (focus?.isConnected) focus.focus({preventScroll: true});
        else add.focus({preventScroll: true});
    });

    async function edit(id) {
        shell('Открываем подключение…', '<p role="status">Загружаем настройки…</p>');
        const token = revision;
        try {
            const record = await A.get(id);
            if (token === revision && dialog.open) form(record);
        } catch (e) {
            if (token === revision && dialog.open) shell('Ошибка загрузки', '<p class="form-error" role="alert">' + E(e.message) + '</p>');
        }
    }

    function form(record = null) {
        const value = record || {
            id: '',
            kind: 'ollama',
            name: '',
            base_url: 'http://127.0.0.1:11434',
            timeout: 60,
            connect_timeout: 10,
            has_api_key: false
        };
        shell(record ? record.name : 'Новый провайдер',
            '<p class="form-hint">Сохраните подключение сейчас; доступность модели можно проверить после сохранения.</p>' +
            '<form class="dialog-form" id="llm-form"><label>Название<input name="name" required maxlength="128" value="' + E(value.name) + '" placeholder="Например, локальная Ollama"></label>' +
            '<div class="form-row"><label>Идентификатор<input name="id" required maxlength="64" pattern="[A-Za-z0-9_-]{1,64}" value="' + E(value.id) + '"' + (record ? ' readonly' : '') + ' placeholder="local" autocomplete="off" spellcheck="false"></label>' +
            '<label>Провайдер<select name="kind"' + (record ? ' disabled' : '') + '><option value="ollama"' + (value.kind === 'ollama' ? ' selected' : '') + '>Ollama</option><option value="openai"' + (value.kind === 'openai' ? ' selected' : '') + '>OpenAI</option></select></label></div>' +
            '<p class="form-hint">Идентификатор и тип после создания изменить нельзя.</p>' +
            '<label>Адрес API<input type="url" name="base_url" required maxlength="2048" value="' + E(value.base_url) + '" autocomplete="off" spellcheck="false"></label>' +
            '<label>API-ключ<input type="password" name="api_key" autocomplete="new-password" placeholder="' + (value.has_api_key ? 'Ключ сохранён · введите новый для замены' : 'Необязательно для локальной Ollama') + '"></label>' +
            '<p class="form-hint">Сохранённый ключ не показывается. Пустое поле оставит его прежним.</p>' +
            (value.has_api_key ? '<label class="llm-clear-key"><input type="checkbox" name="clear_key"> Удалить сохранённый ключ</label>' : '') +
            '<details class="plugin-advanced"><summary>Время ожидания</summary><div class="form-row"><label>Подключение, секунд<input type="number" name="connect_timeout" min="0.01" max="120" step="any" required value="' + E(String(value.connect_timeout)) + '"></label><label>Ответ, секунд<input type="number" name="timeout" min="0.01" max="600" step="any" required value="' + E(String(value.timeout)) + '"></label></div></details>' +
            (record ? '<div class="plugin-status" id="llm-check-status" role="status">Проверка ещё не выполнялась.</div><div class="llm-models" id="llm-models" hidden></div>' : '') +
            '<p class="form-error" role="alert" hidden></p><div class="dialog-actions">' +
            (record ? '<button type="button" class="button danger" id="llm-delete">Удалить</button>' : '') +
            '<button type="button" class="button" id="llm-dismiss">Отмена</button>' +
            (record ? '<button type="button" class="button" id="llm-check">Проверить связь</button>' : '') +
            '<button type="submit" class="button primary">' + (record ? 'Сохранить изменения' : 'Добавить провайдера') + '</button></div>' +
            (record ? '<div class="plugin-confirm" id="llm-confirm" hidden><p>Удалить подключение «' + E(value.name) + '»? Запись исчезнет из Folliant.</p><div class="plugin-confirm-actions"><button type="button" class="button" id="llm-keep">Оставить</button><button type="button" class="button primary" id="llm-delete-final">Да, удалить</button></div></div>' : '') + '</form>');
        const el = content.querySelector('form'), fields = el.elements, message = el.querySelector('.form-error');
        const report = text => {
            message.textContent = text;
            message.hidden = false;
        };
        const toast = text => window.CompanionUI?.toast(text);
        el.querySelector('#llm-dismiss').onclick = () => dialog.close();

        fields.kind.onchange = () => {
            if (record) return;
            const oldDefault = fields.kind.value === 'openai' ? 'http://127.0.0.1:11434' : 'https://api.openai.com/v1';
            if (fields.base_url.value === oldDefault) fields.base_url.value = fields.kind.value === 'openai' ? 'https://api.openai.com/v1' : 'http://127.0.0.1:11434';
        };
        if (fields.clear_key) fields.clear_key.onchange = () => {
            fields.api_key.disabled = fields.clear_key.checked;
            if (fields.clear_key.checked) fields.api_key.value = '';
        };

        async function run(action) {
            if (busy) return;
            busy = true;
            message.hidden = true;
            const controls = [...content.querySelectorAll('button,input,select')];
            const disabled = controls.map(control => control.disabled);
            controls.forEach(control => control.disabled = true);
            el.setAttribute('aria-busy', 'true');
            try {
                await action();
            } catch (e) {
                report(e.message);
            } finally {
                busy = false;
                controls.forEach((control, index) => control.disabled = disabled[index]);
                el.setAttribute('aria-busy', 'false');
            }
        }

        el.onsubmit = event => {
            event.preventDefault();
            if (A.preview || busy) return;
            const body = {
                name: fields.name.value.trim(), base_url: fields.base_url.value.trim(),
                timeout: Number(fields.timeout.value), connect_timeout: Number(fields.connect_timeout.value)
            };
            if (!body.name) return report('Введите название подключения.');
            try {
                const url = new URL(body.base_url);
                if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || /\s/.test(body.base_url)) throw new Error();
            } catch {
                return report('Введите адрес http или https без учётных данных и параметров.');
            }
            if (fields.api_key.value) body.api_key = fields.api_key.value;
            else if (fields.clear_key?.checked) body.api_key = null;
            if (record?.has_api_key && body.base_url !== value.base_url && !Object.hasOwn(body, 'api_key')) return report('При смене адреса укажите новый ключ или удалите сохранённый.');
            if (!record) {
                body.id = fields.id.value.trim();
                body.kind = fields.kind.value;
            }
            run(async () => {
                const saved = record ? await A.update(record.id, body) : await A.create(body);
                fields.api_key.value = '';
                form(saved);
                toast(record ? 'Подключение обновлено' : 'Провайдер добавлен');
                await load();
            });
        };

        if (record) {
            el.querySelector('#llm-check').onclick = () => {
                if (['name', 'base_url', 'timeout', 'connect_timeout'].some(key => String(fields[key].value) !== String(value[key])) || fields.api_key.value || fields.clear_key?.checked) {
                    return report('Сначала сохраните изменения. Проверяется сохранённое подключение.');
                }
                const status = el.querySelector('#llm-check-status'), modelsBox = el.querySelector('#llm-models');
                run(async () => {
                    status.classList.remove('success');
                    status.textContent = 'Подключаемся и получаем список моделей…';
                    modelsBox.hidden = true;
                    try {
                        const models = await A.check(record.id);
                        status.textContent = 'Связь установлена. Доступно моделей: ' + models.length + '.';
                        status.classList.add('success');
                        modelsBox.replaceChildren();
                        for (const model of models) {
                            const item = document.createElement('span');
                            item.textContent = model.id;
                            modelsBox.append(item);
                        }
                        modelsBox.hidden = !models.length;
                    } catch (e) {
                        status.textContent = 'Соединение не подтверждено.';
                        throw e;
                    }
                });
            };
            const confirm = el.querySelector('#llm-confirm');
            el.querySelector('#llm-delete').onclick = () => {
                confirm.hidden = false;
                el.querySelector('#llm-keep').focus();
            };
            el.querySelector('#llm-keep').onclick = () => {
                confirm.hidden = true;
                el.querySelector('#llm-delete').focus();
            };
            el.querySelector('#llm-delete-final').onclick = () => run(async () => {
                await A.remove(record.id);
                dialog.close();
                toast('Подключение удалено');
                await load();
            });
        }
        if (A.preview) {
            el.querySelectorAll('button:not(#llm-dismiss),input,select').forEach(control => control.disabled = true);
            report('В предпросмотре доступно только знакомство с оформлением.');
        }
        fields.name.focus();
    }

    reload.onclick = load;
    add.onclick = () => form();
    window.CompanionLLMSettings = {load};
})();
