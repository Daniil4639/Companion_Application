(() => {
    const A = CompanionMCPAPI, E = CompanionCalendar.escape, I = CompanionIcons.icon;
    const page = document.querySelector('#settings-page'), list = document.querySelector('#plugins-list');
    const dialog = document.querySelector('#plugin-dialog'), content = document.querySelector('#plugin-dialog-content');
    const reload = document.querySelector('#plugins-reload'), add = document.querySelector('#plugin-add');
    let generation = 0, revision = 0, busy = false, focus = null;

    async function load() {
        const token = ++generation;
        const error = document.querySelector('#plugins-error');
        error.hidden = true;
        reload.disabled = true;
        list.setAttribute('aria-busy', 'true');
        document.querySelector('#plugins-state').textContent = 'Загружаем подключения…';
        try {
            const records = await A.list();
            if (token !== generation) return;
            records.sort((a, b) => Number(b.is_internal) - Number(a.is_internal) || a.name.localeCompare(b.name, 'ru'));
            list.replaceChildren();
            document.querySelector('#plugins-state').textContent = A.preview ? 'Пример списка · предпросмотр' : 'Выберите плагин, чтобы открыть настройки';
            for (const record of records) {
                const row = document.createElement('button');
                row.type = 'button';
                row.className = 'plugin-row' + (record.is_internal ? ' internal' : '');
                row.innerHTML = '<span class="plugin-emblem">' + I(record.is_internal ? 'book' : 'spark') + '</span><span class="plugin-copy"><span class="plugin-name"><strong>' + E(record.name) + '</strong>' +
                    (record.is_internal ? '<span class="plugin-tag">Системный плагин</span>' : '') + '</span><small>' + E(record.url) + '</small></span>' + I('chevron-right');
                row.onclick = () => edit(record.id);
                list.append(row);
            }
            if (!records.length) list.innerHTML = '<p class="plugin-empty">Здесь появятся ваши подключения.<br>Добавьте первый плагин кнопкой выше.</p>';
        } catch (e) {
            if (token !== generation) return;
            error.textContent = e.message;
            error.hidden = false;
            document.querySelector('#plugins-state').textContent = 'Не удалось обновить список';
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
        content.innerHTML = '<div class="dialog-body"><div class="dialog-top"><div><div class="dialog-category">' + I('spark') + 'ПЛАГИНЫ ДНЕВНИКА</div><h2 id="plugin-dialog-title">' + E(title) + '</h2></div><button type="button" class="icon-button" data-close aria-label="Закрыть">' + I('close') + '</button></div>' + body + '</div>';
        content.querySelector('[data-close]').onclick = () => {
            if (!busy) dialog.close();
        };
        if (!dialog.open) dialog.showModal();
    }

    dialog.addEventListener('cancel', e => {
        if (busy) e.preventDefault();
    });
    dialog.addEventListener('close', () => {
        revision++;
        if (focus?.isConnected) focus.focus({preventScroll: true});
        else add.focus({preventScroll: true});
    });

    async function edit(id) {
        shell('Открываем плагин…', '<p role="status">Загружаем настройки подключения…</p>');
        const token = revision;
        try {
            const record = await A.get(id);
            if (token === revision && dialog.open) form(record);
        } catch (e) {
            if (token === revision && dialog.open) {
                shell('Не удалось открыть плагин', '<p class="form-error" role="alert">' + E(e.message) + '</p><div class="dialog-actions"><button class="button" id="plugin-retry">Повторить</button></div>');
                content.querySelector('#plugin-retry').onclick = () => edit(id);
            }
        }
    }

    function form(record = null) {
        const internal = !!record?.is_internal;
        const value = record || {id: '', name: '', url: '', connect_timeout: 10, operation_timeout: 30};
        const ro = internal ? ' readonly' : '';
        shell(record ? record.name : 'Новый плагин',
            (internal ? '<span class="plugin-tag">Системный плагин</span><p class="form-hint">Встроенное подключение Folliant. Его настройки управляются приложением и доступны только для просмотра.</p>' : '<p class="form-hint">Укажите название и адрес MCP-сервера. Подключение можно сохранить, даже если сервер сейчас недоступен.</p>') +
            '<form class="dialog-form" id="plugin-form"><label>Название<input name="name" required maxlength="128" value="' + E(value.name) + '"' + ro + '></label>' +
            '<label>Идентификатор<input name="id" required maxlength="64" pattern="[A-Za-z0-9_-]{1,64}" value="' + E(value.id) + '"' + (record ? ' readonly' : '') + ' placeholder="например, notes" autocomplete="off" spellcheck="false"></label><p class="form-hint">Латинские буквы, цифры, дефис и подчёркивание. После создания изменить нельзя.</p>' +
            '<label>Адрес сервера<input type="url" name="url" required maxlength="2048" value="' + E(value.url) + '"' + ro + ' placeholder="http://127.0.0.1:9000/mcp" autocomplete="off" spellcheck="false"></label>' +
            '<p class="form-hint">Streamable HTTP · http или https. Без паролей, параметров запроса и токенов в адресе.</p>' +
            '<details class="plugin-advanced"><summary>Время ожидания</summary><div class="form-row"><label>Подключение, секунд<input type="number" name="connect_timeout" min="0.01" max="300" step="any" required value="' + E(String(value.connect_timeout)) + '"' + ro + '></label><label>Ответ, секунд<input type="number" name="operation_timeout" min="0.01" max="600" step="any" required value="' + E(String(value.operation_timeout)) + '"' + ro + '></label></div></details>' +
            (record ? '<div class="plugin-status" id="plugin-status" role="status">Проверка соединения ещё не выполнялась.</div>' : '') +
            '<p class="form-error" role="alert" hidden></p><div class="dialog-actions">' +
            (record && !internal ? '<button type="button" class="button danger" id="plugin-delete">Удалить</button>' : '') +
            '<button type="button" class="button" id="plugin-dismiss">' + (internal ? 'Закрыть' : 'Отмена') + '</button>' +
            (record ? '<button type="button" class="button" id="plugin-test">Проверить связь</button>' : '') +
            (!internal ? '<button type="submit" class="button primary">' + (record ? 'Сохранить изменения' : 'Добавить плагин') + '</button>' : '') + '</div>' +
            '<div class="plugin-confirm" id="plugin-confirm" hidden><p>Удалить плагин «' + E(value.name) + '»? Подключение исчезнет из дневника. Данные на самом сервере сохранятся.</p><div class="plugin-confirm-actions"><button type="button" class="button" id="plugin-keep">Оставить</button><button type="button" class="button primary" id="plugin-delete-final">Да, удалить</button></div></div></form>');
        const el = content.querySelector('form'), error = el.querySelector('.form-error');
        const report = message => {
            error.textContent = message;
            error.hidden = false;
        };
        const toast = message => window.CompanionUI?.toast(message);
        el.querySelector('#plugin-dismiss').onclick = () => dialog.close();

        async function run(action) {
            if (busy) return;
            busy = true;
            error.hidden = true;
            const controls = [...content.querySelectorAll('button,input')];
            const disabled = controls.map(control => control.disabled);
            controls.forEach(control => control.disabled = true);
            el.setAttribute('aria-busy', 'true');
            try {
                await action();
            } catch (e) {
                report(e.message);
            } finally {
                busy = false;
                controls.forEach((control, i) => control.disabled = disabled[i]);
                el.setAttribute('aria-busy', 'false');
            }
        }

        el.onsubmit = event => {
            event.preventDefault();
            if (internal || A.preview || busy) return;
            const fields = el.elements;
            const body = {
                name: fields.name.value.trim(),
                url: fields.url.value.trim(),
                connect_timeout: Number(fields.connect_timeout.value),
                operation_timeout: Number(fields.operation_timeout.value)
            };
            if (!body.name) return report('Введите название плагина.');
            try {
                const url = new URL(body.url);
                if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || /\s/.test(body.url)) throw new Error();
            } catch {
                return report('Введите адрес http или https без пароля, параметров запроса и фрагмента.');
            }
            if (!record) body.id = fields.id.value.trim();
            run(async () => {
                const saved = record ? await A.update(record.id, body) : await A.create(body);
                // Replace the form so the saved connection can be tested immediately.
                form(saved);
                toast(record ? 'Настройки плагина сохранены' : 'Плагин добавлен');
                await load();
            });
        };
        if (record) {
            el.querySelector('#plugin-test').onclick = () => {
                if (!internal && ['name', 'url', 'connect_timeout', 'operation_timeout'].some(key => String(el.elements[key].value) !== String(value[key]))) {
                    report('Сначала сохраните изменения — проверяется сохранённое подключение.');
                    return;
                }
                const status = el.querySelector('#plugin-status');
                run(async () => {
                    status.classList.remove('success');
                    status.textContent = 'Проверяем соединение и получаем список инструментов…';
                    try {
                        const result = await A.test(record.id);
                        status.textContent = 'Связь установлена. Доступно инструментов: ' + result.available_tools + '.';
                        status.classList.add('success');
                    } catch (e) {
                        status.textContent = 'Соединение не подтверждено.';
                        throw e;
                    }
                });
            };
        }
        if (record && !internal) {
            const confirm = el.querySelector('#plugin-confirm');
            el.querySelector('#plugin-delete').onclick = () => {
                confirm.hidden = false;
                el.querySelector('#plugin-keep').focus();
                confirm.scrollIntoView({block: 'nearest'});
            };
            el.querySelector('#plugin-keep').onclick = () => {
                confirm.hidden = true;
                el.querySelector('#plugin-delete').focus();
            };
            el.querySelector('#plugin-delete-final').onclick = () => run(async () => {
                await A.remove(record.id);
                dialog.close();
                toast('Плагин удалён');
                await load();
            });
        }
        if (A.preview) {
            el.querySelectorAll('button:not(#plugin-dismiss),input').forEach(control => control.disabled = true);
            report('В предпросмотре доступно только знакомство с оформлением.');
        }
        (internal ? content.querySelector('[data-close]') : el.elements.name).focus();
    }

    reload.onclick = load;
    add.onclick = () => form();
    const shortcuts = [...page.querySelectorAll('[data-section]')];
    const sections = shortcuts.map(button => document.getElementById(button.dataset.section));
    shortcuts.forEach((button, index) => button.onclick = () => {
        const target = sections[index];
        page.scrollTo({
            top: page.scrollTop + target.getBoundingClientRect().top - page.getBoundingClientRect().top - 74,
            behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'
        });
        target.focus({preventScroll: true});
    });

    function highlight() {
        const top = page.getBoundingClientRect().top + 90;
        let active = 0;
        sections.forEach((section, index) => {
            if (section.getBoundingClientRect().top <= top) active = index;
        });
        if (page.scrollTop > 0 && page.scrollTop + page.clientHeight >= page.scrollHeight - 3) active = sections.length - 1;
        shortcuts.forEach((button, index) => {
            if (index === active) button.setAttribute('aria-current', 'location'); else button.removeAttribute('aria-current');
        });
    }

    page.addEventListener('scroll', highlight, {passive: true});
    window.CompanionMCPSettings = {
        load: () => {
            highlight();
            return load();
        }
    };
})();
