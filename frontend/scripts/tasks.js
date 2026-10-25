(() => {
    const A = CompanionTasksAPI, D = CompanionTaskDialog, C = CompanionCalendar, E = C.escape;
    const board = document.querySelector('#kanban-board'), error = document.querySelector('#tasks-error');
    const statuses = D.statuses, priorities = D.priorities;
    let rows = [], generation = 0, controller, loading = false, saving = false, valid = false, dragId = null;
    const today = () => C.dateKey(new CompanionTime.Date());
    const dateLabel = value => new CompanionTime.Date(value).toLocaleDateString('ru-RU', {
        day: 'numeric',
        month: 'short'
    });
    const column = status => rows.filter(t => t.status === status).sort((a, b) => a.position - b.position);

    function message(text) {
        error.textContent = text || '';
        error.hidden = !text;
    }

    function controls() {
        board.inert = loading || saving || !valid;
        board.setAttribute('aria-busy', String(loading || saving));
        document.querySelector('#new-task').disabled = loading || saving || !valid || CompanionAPI.preview;
        document.querySelector('#reload-tasks').disabled = loading || saving;
    }

    function render() {
        board.innerHTML = Object.entries(statuses).map(([status, label]) => {
            const items = column(status);
            return '<section class="kanban-column" data-status="' + status + '" aria-label="' + label + '"><header><h2>' + label + '</h2><span class="count-badge">' + items.length + '</span><button class="icon-button task-add" data-add="' + status + '" aria-label="Добавить задачу: ' + label + '" ' + (CompanionAPI.preview ? 'disabled' : '') + '>+</button></header><div class="kanban-cards" data-drop="' + status + '">' +
                items.map((t, index) => '<article class="task-card ' + (status === 'DONE' ? 'task-done' : '') + '" data-task="' + t.id + '" draggable="true">' +
                    '<div class="task-card-top"><span class="priority priority-' + t.priority + '">' + priorities[t.priority] + '</span><span class="task-grip" aria-hidden="true">⠿</span></div>' +
                    '<button class="task-open" data-open="' + t.id + '">' + E(t.title) + '</button>' +
                    (t.description ? '<p class="task-excerpt">' + E(t.description) + '</p>' : '') +
                    '<div class="task-dates">' + (t.scheduled_date ? '<span>План · ' + E(dateLabel(t.scheduled_date)) + '</span>' : '') +
                    (t.due_date ? '<span class="' + (status !== 'DONE' && t.due_date < today() ? 'overdue' : '') + '">Срок · ' + E(dateLabel(t.due_date)) + '</span>' : '') + '</div>' +
                    '<div class="task-order"><button class="text-button" data-up="' + t.id + '" aria-label="Выше: ' + E(t.title) + '" ' + (index === 0 ? 'disabled' : '') + '>↑</button><button class="text-button" data-down="' + t.id + '" aria-label="Ниже: ' + E(t.title) + '" ' + (index === items.length - 1 ? 'disabled' : '') + '>↓</button><button class="text-button" data-open="' + t.id + '">Изменить</button></div></article>').join('') +
                (!items.length ? '<p class="column-empty">Место для новой задачи<br><small>Добавьте или перетащите карточку</small></p>' : '') + '</div></section>';
        }).join('');
        board.querySelectorAll('[data-open]').forEach(b => b.onclick = () => D.edit(b.dataset.open));
        board.querySelectorAll('[data-add]').forEach(b => b.onclick = () => D.create(b.dataset.add));
        for (const direction of ['up', 'down']) board.querySelectorAll('[data-' + direction + ']').forEach(b => b.onclick = () => {
            const task = rows.find(t => t.id === b.dataset[direction]);
            move(task.id, task.status, task.position + (direction === 'up' ? -1 : 1));
        });
        board.querySelectorAll('[data-task]').forEach(card => {
            card.ondragstart = e => {
                if (loading || saving) {
                    e.preventDefault();
                    return;
                }
                dragId = card.dataset.task;
                e.dataTransfer.effectAllowed = 'move';
                e.dataTransfer.setData('text/plain', dragId);
                card.classList.add('dragging');
            };
            card.ondragend = clearDrag;
        });
        board.querySelectorAll('[data-drop]').forEach(target => {
            target.ondragover = e => {
                if (!dragId || saving || loading) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                board.querySelectorAll('.drop-active,.drop-before,.drop-after').forEach(el => el.classList.remove('drop-active', 'drop-before', 'drop-after'));
                target.classList.add('drop-active');
                const card = e.target.closest('[data-task]');
                if (card && card.dataset.task !== dragId) card.classList.add(e.clientY < card.getBoundingClientRect().top + card.offsetHeight / 2 ? 'drop-before' : 'drop-after');
                // Allow dragging to cards outside the visible part of a long column.
                const rect = target.getBoundingClientRect();
                if (e.clientY < rect.top + 45) target.scrollTop -= 15;
                if (e.clientY > rect.bottom - 45) target.scrollTop += 15;
                const boardRect = board.getBoundingClientRect();
                if (e.clientX < boardRect.left + 40) board.scrollLeft -= 15;
                if (e.clientX > boardRect.right - 40) board.scrollLeft += 15;
            };
            target.ondrop = e => {
                if (!dragId || saving || loading) return;
                e.preventDefault();
                const id = dragId, status = target.dataset.drop, others = column(status).filter(t => t.id !== id),
                    card = e.target.closest('[data-task]');
                let position = others.length;
                if (card) {
                    if (card.dataset.task === id) {
                        clearDrag();
                        return;
                    }
                    position = others.findIndex(t => t.id === card.dataset.task);
                    if (e.clientY >= card.getBoundingClientRect().top + card.offsetHeight / 2) position++;
                }
                clearDrag();
                move(id, status, position);
            };
        });
        controls();
    }

    function clearDrag() {
        dragId = null;
        board.querySelectorAll('.dragging,.drop-active,.drop-before,.drop-after').forEach(el => el.classList.remove('dragging', 'drop-active', 'drop-before', 'drop-after'));
    }

    async function load() {
        const token = ++generation;
        controller?.abort();
        controller = new AbortController();
        loading = true;
        valid = false;
        controls();
        message('');
        document.querySelector('#tasks-state').textContent = 'Загружаем задачи…';
        try {
            const result = await A.list({}, controller.signal);
            if (token !== generation) return;
            rows = result;
            valid = true;
            render();
            document.querySelector('#tasks-state').textContent = rows.length ? 'Перетаскивайте карточки. Статус также можно изменить в форме задачи.' : 'Начните с идеи — даты можно добавить позже.';
        } catch (e) {
            if (e.name === 'AbortError' || token !== generation) return;
            message(e.message);
            document.querySelector('#tasks-state').textContent = 'Не удалось обновить доску';
        } finally {
            if (token === generation) {
                loading = false;
                controls();
            }
        }
    }

    async function move(id, status, position) {
        if (saving || loading || !valid) return;
        saving = true;
        controls();
        message('');
        try {
            await A.move(id, status, position);
            window.dispatchEvent(new CustomEvent('tasks-changed', {detail: 'Задача перемещена'}));
        } catch (e) {
            message(e.message);
        } finally {
            saving = false;
            controls();
        }
    }

    document.querySelector('#new-task').onclick = () => D.create();
    document.querySelector('#reload-tasks').onclick = load;
    window.addEventListener('tasks-changed', () => {
        if (!document.querySelector('#tasks-page').hidden) load();
    });
    render();

    // Today's panel and mini-calendar markers use the same Task IDs.
    let calendarRows = [], calendarGeneration = 0, calendarController;

    function chips(tasks, key) {
        return tasks.filter(t => t.scheduled_date === key || t.due_date === key).map(t => {
            const planned = t.scheduled_date === key, due = t.due_date === key;
            return '<button class="calendar-task ' + (due ? 'has-deadline ' : '') + (t.status === 'DONE' ? 'task-done' : '') + '" data-open-task="' + t.id + '" title="' + E(t.title) + '"><span>' + E(t.title) + '</span><small>' + (planned ? 'План' : '') + (planned && due ? ' · ' : '') + (due ? 'Срок' : '') + (t.status === 'DONE' ? ' · ✓' : '') + '</small></button>';
        }).join('');
    }

    function bindCalendar(root) {
        root.querySelectorAll('[data-open-task]').forEach(b => b.onclick = () => D.edit(b.dataset.openTask));
    }

    async function loadCalendar(first, last, onRender) {
        const token = ++calendarGeneration;
        calendarController?.abort();
        calendarController = new AbortController();
        calendarRows = [];
        const todayKey = today(), start = C.dateKey(first), end = C.dateKey(last);
        const agenda = document.querySelector('#today-tasks'), counter = document.querySelector('#today-tasks-count');
        counter.textContent = '—';
        agenda.textContent = 'Загружаем задачи…';
        try {
            const signal = calendarController.signal;
            const [week, todayRows] = await Promise.all([A.list({date_from: start, date_to: end}, signal),
                todayKey >= start && todayKey <= end ? Promise.resolve([]) : A.list({
                    date_from: todayKey,
                    date_to: todayKey
                }, signal)]);
            const result = [...new Map([...week, ...todayRows].map(t => [t.id, t])).values()];
            if (token !== calendarGeneration) return;
            calendarRows = result;
            counter.textContent = result.filter(t => t.scheduled_date === todayKey || t.due_date === todayKey).length;
            agenda.innerHTML = (chips(result, todayKey) || '<p class="form-hint">Нет задач с датой или дедлайном на сегодня.</p>');
            bindCalendar(agenda);
            onRender?.();
        } catch (e) {
            if (e.name === 'AbortError' || token !== calendarGeneration) return;
            counter.textContent = '—';
            agenda.textContent = e.message + ' ';
            const retry = document.createElement('button');
            retry.className = 'text-button';
            retry.textContent = 'Повторить';
            retry.onclick = () => loadCalendar(first, last, onRender);
            agenda.append(retry);
        }
    }

    window.CompanionTasks = {
        load,
        loadCalendar,
        hasDate: key => calendarRows.some(t => t.scheduled_date === key || t.due_date === key)
    };
})();
