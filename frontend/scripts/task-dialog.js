(() => {
    const A = CompanionTasksAPI, E = CompanionCalendar.escape;
    const statuses = {BACKLOG: 'Идеи', TODO: 'К выполнению', IN_PROGRESS: 'В работе', DONE: 'Готово'};
    const priorities = {Low: 'Низкий', Medium: 'Средний', High: 'Высокий'};
    const dialog = document.querySelector('#task-dialog'), content = document.querySelector('#task-dialog-content');
    let busy = false, revision = 0, focus = null;
    const options = (items, value) => Object.entries(items).map(([key, label]) => '<option value="' + key + '" ' + (key === value ? 'selected' : '') + '>' + label + '</option>').join('');

    function shell(title, body) {
        revision++;
        if (!dialog.open) focus = document.activeElement;
        content.innerHTML = '<div class="dialog-body"><div class="dialog-top"><div><div class="dialog-category">ЗАДАЧА</div><h2 id="task-dialog-title">' + E(title) + '</h2></div><button class="icon-button" data-close aria-label="Закрыть задачу">×</button></div>' + body + '</div>';
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
    });

    async function edit(id) {
        shell('Открываем задачу…', '<p role="status">Загрузка…</p>');
        const token = revision;
        try {
            const task = await A.get(id);
            if (token === revision && dialog.open) form(task);
        } catch (error) {
            if (token === revision) shell('Не удалось открыть задачу', '<p class="form-error" role="alert">' + E(error.message) + '</p>');
        }
    }

    function form(task = null, status = 'BACKLOG', scheduledDate = null) {
        if (CompanionAPI.preview) return window.CompanionUI.toast('Создание задач доступно в запущенном приложении.');
        const value = task || {
            title: '',
            description: '',
            status,
            priority: 'Medium',
            scheduled_date: scheduledDate,
            due_date: null
        };
        shell(task ? 'Страница задачи' : 'Новая задача',
            '<form class="dialog-form" id="task-form"><label>Название задачи<input name="title" required maxlength="255" value="' + E(value.title) + '" autofocus></label>' +
            '<label>Описание задачи<textarea name="description" rows="3" maxlength="10000">' + E(value.description || '') + '</textarea></label>' +
            '<div class="form-row"><label>Статус<select name="status">' + options(statuses, value.status) + '</select></label><label>Приоритет<select name="priority">' + options(priorities, value.priority) + '</select></label></div>' +
            '<div class="form-row"><label>Запланировано на<input type="date" name="scheduled_date" value="' + E(value.scheduled_date || '') + '"></label><label>Дедлайн<input type="date" name="due_date" value="' + E(value.due_date || '') + '"></label></div>' +
            '<p class="form-hint">Даты необязательны. Задача появится в календаре без создания события.</p>' +
            (value.completed_at ? '<p class="form-hint">Завершено: ' + E(new globalThis.Date(value.completed_at).toLocaleString('ru-RU', {timeZone: CompanionTime.zone})) + '</p>' : '') +
            '<div class="form-error" role="alert" hidden></div><div class="dialog-actions">' +
            (task ? '<button type="button" class="button danger" id="task-delete">Удалить задачу</button>' : '') +
            '<button type="button" class="button" id="task-dismiss">Отмена</button><button type="submit" class="button primary">Сохранить задачу</button></div>' +
            '<div id="task-delete-confirm" class="task-delete-confirm" hidden><p>Удалить задачу без возможности восстановления?</p><button type="button" class="button" id="task-keep">Оставить</button> <button type="button" class="button primary" id="task-delete-final">Да, удалить</button></div></form>');
        const el = content.querySelector('form');
        el.querySelector('#task-dismiss').onclick = () => dialog.close();

        async function save(action, message) {
            if (busy) return;
            busy = true;
            const controls = [...content.querySelectorAll('button,input,select,textarea')];
            controls.forEach(e => e.disabled = true);
            const error = el.querySelector('.form-error');
            error.hidden = true;
            try {
                await action();
                dialog.close();
                window.dispatchEvent(new CustomEvent('tasks-changed', {detail: message}));
            } catch (e) {
                error.textContent = e.message;
                error.hidden = false;
            } finally {
                busy = false;
                controls.forEach(e => e.disabled = false);
            }
        }

        el.onsubmit = e => {
            e.preventDefault();
            const fd = new FormData(el);
            const body = {
                title: fd.get('title').trim(),
                description: fd.get('description').trim() || null,
                status: fd.get('status'),
                priority: fd.get('priority'),
                scheduled_date: fd.get('scheduled_date') || null,
                due_date: fd.get('due_date') || null
            };
            if (!body.title) {
                const error = el.querySelector('.form-error');
                error.textContent = 'Введите название задачи.';
                error.hidden = false;
                return;
            }
            save(() => task ? A.update(task.id, body) : A.create(body), task ? 'Задача сохранена' : 'Задача создана');
        };
        if (task) {
            const box = el.querySelector('#task-delete-confirm');
            el.querySelector('#task-delete').onclick = () => {
                box.hidden = false;
                el.querySelector('#task-delete-final').focus();
            };
            el.querySelector('#task-keep').onclick = () => {
                box.hidden = true;
            };
            el.querySelector('#task-delete-final').onclick = () => save(() => A.remove(task.id), 'Задача удалена');
        }
        el.elements.title.focus();
    }

    window.CompanionTaskDialog = {
        edit,
        create: (status, scheduledDate) => form(null, status, scheduledDate),
        statuses,
        priorities
    };
})();
