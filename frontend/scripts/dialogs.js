(() => {
    const Date = CompanionTime.Date;
    const C = CompanionCalendar, A = CompanionAPI, I = CompanionIcons.icon, E = C.escape;
    const dialog = document.querySelector('#event-dialog'), content = document.querySelector('#dialog-content');
    let revision = 0, lastFocus = null, busy = false;
    const titleDate = d => d.toLocaleDateString('ru-RU', {day: 'numeric', month: 'long', year: 'numeric'});
    const zone = () => CompanionTime.zone;

    function changed(message) {
        dialog.close();
        window.dispatchEvent(new CustomEvent('calendar-changed', {detail: message}));
    }

    function shell(title, body, tag = 'СОБЫТИЕ') {
        revision++;
        if (!dialog.open) lastFocus = document.activeElement;
        content.innerHTML = '<div class="dialog-body"><div class="dialog-top"><div><div class="dialog-category">' + I('calendar') + E(tag) + '</div><h2 id="dialog-title">' + E(title) + '</h2></div><button class="icon-button" data-close aria-label="Закрыть">' + I('close') + '</button></div>' + body + '</div>';
        content.querySelector('[data-close]').onclick = () => {
            if (!busy) dialog.close();
        };
        if (!dialog.open) dialog.showModal();
        content.querySelectorAll('[data-dismiss]').forEach(b => b.onclick = () => dialog.close());
        return revision;
    }

    dialog.addEventListener('cancel', event => {
        if (busy) event.preventDefault();
    });
    dialog.addEventListener('close', () => {
        revision++;
        if (lastFocus?.isConnected) lastFocus.focus({preventScroll: true});
    });
    dialog.addEventListener('click', event => {
        if (event.target === dialog && !busy) {
            const r = dialog.getBoundingClientRect();
            if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close();
        }
    });

    function error(message) {
        const el = content.querySelector('.form-error');
        if (el) {
            el.textContent = message;
            el.hidden = false;
        }
    }

    async function perform(button, callback) {
        if (busy) return;
        busy = true;
        const buttons = [...content.querySelectorAll('button')].map(b => [b, b.disabled]);
        buttons.forEach(([b]) => b.disabled = true);
        button.classList.add('busy-button');
        try {
            await callback();
        } catch (e) {
            error(e.message);
        } finally {
            busy = false;
            buttons.forEach(([b, disabled]) => {
                if (b.isConnected) b.disabled = disabled;
            });
            button.classList.remove('busy-button');
        }
    }

    function localValue(value) {
        const date = new Date(value);
        if (!Number.isFinite(+date) || C.localInput(date) !== value) throw new Error('Указанное местное время не существует. Выберите другое время.');
        CompanionTime.validateWall(date);
        return date;
    }

    const endOptions = '<option value="never">Без окончания</option><option value="count">После повторений</option><option value="until">До даты</option>';

    function form(start = new Date(), series = null) {
        if (A.preview) return window.CompanionUI.toast('В предпросмотре события приведены для примера.');
        const edit = !!series, s = edit ? new Date(series.start_at) : start,
            f = edit ? new Date(series.finish_at) : new Date(+s + 36e5);
        const rule = series?.recurrence_rule;
        shell(edit ? (rule ? 'Изменить всю серию' : 'Изменить событие') : 'Новое событие',
            '<form class="dialog-form" id="event-form"><label>Название<input name="title" required maxlength="255" autocomplete="off" value="' + E(series?.title || '') + '" placeholder="Что запланируем?" autofocus></label>' +
            '<div class="form-row"><label>Начало<input type="datetime-local" name="start" required value="' + C.localInput(s) + '"></label><label>Окончание<input type="datetime-local" name="finish" required value="' + C.localInput(f) + '"></label></div>' +
            '<p class="form-hint">Время календаря: ' + E(zone()) + (edit && series.timezone !== zone() ? '. Повторения — в зоне ' + E(series.timezone) : '') + '.</p>' +
            '<label>Тип события<select name="category">' + Object.entries(CompanionCategories).map(([key, cat]) => '<option value="' + key + '" ' + (key === (series?.category || 'default') ? 'selected' : '') + '>' + E(cat.label) + '</option>').join('') + '</select></label><div id="category-preview" class="category-preview" aria-hidden="true"></div>' +
            '<label>Описание<textarea name="description" rows="3" placeholder="Детали, которые хочется запомнить">' + E(series?.description || '') + '</textarea></label>' +
            '<label>Повторение<select name="frequency"><option value="">Не повторять</option><option value="daily">Каждый день</option><option value="weekly">Каждую неделю</option><option value="monthly">Каждый месяц</option><option value="yearly">Каждый год</option></select></label>' +
            '<div class="repeat-settings" id="repeat-settings" hidden><div class="form-row"><label>Интервал<input name="interval" type="number" min="1" max="1000" value="' + (rule?.interval || 1) + '"></label><label>Окончание повторений<select name="ending">' + endOptions + '</select></label></div>' +
            '<div id="weekdays" hidden><p class="form-hint">Дни недели</p><div class="weekday-options">' + ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'].map((v, i) => '<label><input type="checkbox" name="weekday" value="' + v + '"><span>' + C.WEEKDAYS[i] + '</span></label>').join('') + '</div></div>' +
            '<label id="count-field" hidden>Количество повторений<input name="count" type="number" min="1" max="100000" value="' + (rule?.count || 10) + '"></label>' +
            '<label id="until-field" hidden>Последняя дата<input name="until" type="date" value="' + (rule?.until ? C.dateKey(new Date(rule.until)) : C.dateKey(C.addDays(s, 30))) + '"></label></div>' +
            '<p class="form-hint">' + (edit ? 'Изменения применятся ко всему событию' + (rule ? ' и его повторениям' : '') + '.' : 'Тип задаёт цвет и значок события.') + '</p>' +
            '<div class="form-error" role="alert" hidden></div><label class="confirm-reset" id="reset-label" hidden><input type="checkbox" name="reset"><span>Сбросить все переносы и отмены этой серии и применить изменения.</span></label>' +
            '<div class="dialog-actions"><button type="button" class="button" data-dismiss>Отмена</button><button type="submit" class="button primary">' + (edit ? 'Сохранить' : 'Создать событие') + '</button></div></form>');
        const el = content.querySelector('form'), freq = el.elements.frequency, end = el.elements.ending;
        freq.value = rule?.frequency || '';
        end.value = rule?.count ? 'count' : rule?.until ? 'until' : 'never';
        const defaultDays = rule?.by_weekday || [['SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA'][s.getDay()]];
        el.querySelectorAll('[name=weekday]').forEach(input => input.checked = defaultDays.includes(input.value));

        function repeatUI() {
            content.querySelector('#repeat-settings').hidden = !freq.value;
            content.querySelector('#weekdays').hidden = freq.value !== 'weekly';
            content.querySelector('#count-field').hidden = end.value !== 'count';
            content.querySelector('#until-field').hidden = end.value !== 'until';
        }

        function categoryPreview() {
            const cat = CompanionCategories[el.elements.category.value] || CompanionCategories.default;
            const preview = content.querySelector('#category-preview');
            preview.style.color = cat.color;
            preview.style.background = cat.background;
            preview.innerHTML = I(cat.icon) + '<span>' + E(cat.label) + '</span>';
        }

        el.elements.category.onchange = categoryPreview;
        categoryPreview();
        freq.onchange = repeatUI;
        end.onchange = repeatUI;
        repeatUI();
        const ruleSnapshot = () => JSON.stringify([freq.value, end.value, el.elements.interval.value, el.elements.count.value, el.elements.until.value, [...el.querySelectorAll('[name=weekday]:checked')].map(b => b.value)]);
        const initialRule = ruleSnapshot();
        el.elements.start.addEventListener('change', () => {
            const ns = new Date(el.elements.start.value), nf = new Date(el.elements.finish.value);
            if (Number.isFinite(+ns) && nf <= ns) el.elements.finish.value = C.localInput(new Date(+ns + 36e5));
        });
        el.onsubmit = async event => {
            event.preventDefault();
            content.querySelector('.form-error').hidden = true;
            const button = el.querySelector('[type=submit]');
            await perform(button, async () => {
                const fd = new FormData(el), startDate = localValue(fd.get('start')),
                    finishDate = localValue(fd.get('finish'));
                const startISO = edit && fd.get('start') === C.localInput(s) ? series.start_at : startDate.toISOString();
                const finishISO = edit && fd.get('finish') === C.localInput(f) ? series.finish_at : finishDate.toISOString();
                if (new globalThis.Date(finishISO) <= new globalThis.Date(startISO)) throw new Error('Окончание должно быть позже начала.');
                const title = fd.get('title').trim();
                if (!title) throw new Error('Введите название события.');
                let nextRule = null;
                if (freq.value) {
                    nextRule = {
                        ...(rule?.frequency === freq.value ? rule : {}),
                        frequency: freq.value,
                        interval: Number(fd.get('interval')),
                        count: null,
                        until: null
                    };
                    if (freq.value === 'weekly') {
                        const days = fd.getAll('weekday');
                        if (!days.length) throw new Error('Выберите хотя бы один день недели.');
                        nextRule.by_weekday = days;
                    }
                    if (end.value === 'count') {
                        nextRule.count = Number(fd.get('count'));
                        if (!Number.isInteger(nextRule.count) || nextRule.count < 1) throw new Error('Укажите количество повторений.');
                    }
                    if (end.value === 'until') {
                        if (!fd.get('until')) throw new Error('Выберите последнюю дату повторения.');
                        const until = new Date(fd.get('until') + 'T23:59:59');
                        if (until < startDate) throw new Error('Последняя дата не может быть раньше начала.');
                        nextRule.until = until.toISOString();
                    }
                }
                if (edit && ruleSnapshot() === initialRule) nextRule = rule;
                const payload = {
                    title,
                    category: fd.get('category'),
                    description: fd.get('description').trim() || null,
                    start_at: startISO,
                    finish_at: finishISO,
                    timezone: series?.timezone || zone(),
                    recurrence_rule: nextRule || null
                };
                try {
                    if (edit) await A.update(series.id, payload, fd.get('reset') === 'on'); else await A.create(payload);
                    changed(edit ? 'Изменения сохранены' : 'Событие добавлено');
                } catch (e) {
                    if (e.status === 409 && e.detail.includes('reset_exceptions')) {
                        content.querySelector('#reset-label').hidden = false;
                        throw new Error('У серии есть переносы или отмены. Подтвердите их сброс, чтобы изменить время или повторение.');
                    }
                    throw e;
                }
            });
        };
        requestAnimationFrame(() => el.elements.title.focus());
    }

    async function details(occurrence, seriesOnly = false) {
        const s = new Date(occurrence.start_at), f = new Date(occurrence.finish_at);
        const token = shell(occurrence.title,
            '<div class="detail-line">' + I('calendar') + '<div><strong>' + E(titleDate(s)) + '</strong>' + (C.sameDay(s, f) ? '' : ' — ' + E(titleDate(f))) + '</div></div>' +
            '<div class="detail-line">' + I('clock') + '<div><strong>' + C.time(s) + ' — ' + C.time(f) + '</strong><small>' + E(zone()) + '</small></div></div>' +
            '<div id="category-detail" class="detail-line"></div><div id="repeat-detail" class="detail-line"></div><p class="dialog-description">' + E(occurrence.description || 'Пока без дополнительных заметок.') + '</p>' +
            '<div class="form-error" role="alert" hidden></div><div id="detail-actions"><p class="form-hint">Загружаем сведения…</p></div>');
        try {
            const series = await A.get(occurrence.event_series_id);
            if (token !== revision || !dialog.open) return;
            const recurring = !!series.recurrence_rule;
            const cat = CompanionCategories[series.category] || CompanionCategories.default;
            const categoryDetail = content.querySelector('#category-detail');
            categoryDetail.style.color = cat.color;
            categoryDetail.innerHTML = I(cat.icon) + '<div>' + E(cat.label) + '</div>';
            const labels = {
                daily: 'Ежедневное повторение',
                weekly: 'Еженедельное повторение',
                monthly: 'Ежемесячное повторение',
                yearly: 'Ежегодное повторение'
            };
            content.querySelector('#repeat-detail').innerHTML = recurring ? I('repeat') + '<div>' + E(labels[series.recurrence_rule.frequency]) + '</div>' : '';
            content.querySelector('#detail-actions').innerHTML = '<div class="dialog-actions"><button class="button" id="edit-event" ' + (A.preview ? 'disabled' : '') + '>' + I('edit') + (recurring ? 'Изменить серию' : 'Изменить') + '</button><button class="button primary" id="move-event" ' + (A.preview ? 'disabled' : '') + '>' + I('arrow') + 'Перенести</button></div>' +
                '<div class="secondary-actions"><button class="text-button" id="cancel-event" ' + (A.preview ? 'disabled' : '') + '>Отменить ' + (recurring ? 'этот повтор' : 'событие') + '</button><button class="text-button" id="delete-event" ' + (A.preview ? 'disabled' : '') + '>' + (recurring ? 'Удалить всю серию' : 'Удалить событие') + '</button></div>';
            if (seriesOnly) {
                content.querySelector('#move-event').hidden = true;
                content.querySelector('#cancel-event').hidden = true;
            }
            content.querySelector('#edit-event').onclick = () => form(s, series);
            content.querySelector('#move-event').onclick = () => move(occurrence);
            content.querySelector('#cancel-event').onclick = () => confirm('Отменить событие?', '«' + occurrence.title + '» исчезнет из расписания.' + (recurring ? ' Остальные повторения сохранятся.' : ''), 'Отменить событие', () => A.cancel(occurrence), 'Событие отменено');
            content.querySelector('#delete-event').onclick = () => confirm(recurring ? 'Удалить всю серию?' : 'Удалить событие?', '«' + series.title + '» будет удалено' + (recurring ? ' вместе со всеми повторениями и переносами' : '') + '.', 'Удалить', () => A.remove(series.id), 'Событие удалено');
        } catch (e) {
            if (token === revision) {
                content.querySelector('#detail-actions').innerHTML = '';
                error(e.message);
            }
        }
    }

    function move(o) {
        shell('Перенести событие', '<p class="form-hint">' + E(o.title) + '</p><form class="dialog-form"><div class="form-row"><label>Новое начало<input type="datetime-local" name="start" value="' + C.localInput(new Date(o.start_at)) + '" required></label><label>Новое окончание<input type="datetime-local" name="finish" value="' + C.localInput(new Date(o.finish_at)) + '" required></label></div><p class="form-hint">Часовой пояс: ' + E(zone()) + '. Остальные повторения не изменятся.</p><div class="form-error" role="alert" hidden></div><div class="dialog-actions"><button type="button" class="button" data-dismiss>Назад</button><button class="button primary" type="submit">Перенести</button></div></form>');
        content.querySelector('[data-dismiss]').onclick = () => details(o);
        content.querySelector('form').onsubmit = async e => {
            e.preventDefault();
            const fd = new FormData(e.target);
            await perform(e.target.querySelector('[type=submit]'), async () => {
                const s = localValue(fd.get('start')), f = localValue(fd.get('finish'));
                const startISO = fd.get('start') === C.localInput(new Date(o.start_at)) ? o.start_at : s.toISOString(),
                    finishISO = fd.get('finish') === C.localInput(new Date(o.finish_at)) ? o.finish_at : f.toISOString();
                if (new globalThis.Date(finishISO) <= new globalThis.Date(startISO)) throw new Error('Окончание должно быть позже начала.');
                await A.move(o, {start_at: startISO, finish_at: finishISO});
                changed('Событие перенесено');
            });
        };
    }

    function confirm(title, message, label, action, success) {
        shell(title, '<p class="confirm-message">' + E(message) + '</p><div class="form-error" role="alert" hidden></div><div class="dialog-actions"><button class="button" data-dismiss>Назад</button><button class="button primary" id="confirm-action">' + E(label) + '</button></div>');
        content.querySelector('#confirm-action').onclick = e => perform(e.currentTarget, async () => {
            await action();
            changed(success);
        });
    }

    window.CompanionDialogs = {form, details};
})();
