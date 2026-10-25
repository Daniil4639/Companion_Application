/* Pure date/navigation/layout functions, also exercised with node:test. */
(() => {
    const Date = CompanionTime.Date;
    const MONTHS = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
    const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
    const pad = n => String(n).padStart(2, '0');
    const dayStart = d => new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
    const weekStart = d => addDays(dayStart(d), -((d.getDay() + 6) % 7));
    const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
    const dateKey = d => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
    const time = d => pad(d.getHours()) + ':' + pad(d.getMinutes());
    const localInput = d => dateKey(d) + 'T' + time(d);
    const monthGrid = (year, month) => {
        const first = weekStart(new Date(year, month, 1));
        return Array.from({length: 42}, (_, i) => addDays(first, i));
    };
    const selectMonth = (year, month, today = new Date()) => year === today.getFullYear() && month === today.getMonth() ? dayStart(today) : new Date(year, month, 1);
    const yearPage = year => Math.floor(year / 12) * 12;
    const navigate = (anchor, view, direction) => {
        if (view === 'week') return addDays(anchor, 7 * direction);
        return new Date(anchor.getFullYear() + (view === 'months' ? 1 : 12) * direction, anchor.getMonth(), 1);
    };

    function layoutEvents(occurrences, day, hourHeight = 64) {
        const next = addDays(day, 1), maxHeight = 24 * hourHeight;
        const minute = d => d.getHours() * 60 + d.getMinutes() + d.getSeconds() / 60;
        const items = occurrences.filter(o => new Date(o.start_at) < next && new Date(o.finish_at) > day).map(o => {
            const start = new Date(o.start_at), end = new Date(o.finish_at);
            const a = start < day ? 0 : minute(start), b = end >= next ? 1440 : minute(end);
            const top = Math.min(a * hourHeight / 60, maxHeight - 26);
            const height = Math.min(maxHeight - top, Math.max(26, (b - a) * hourHeight / 60 - 3));
            return {
                event: o,
                top,
                height,
                end: top + height + 3,
                lane: 0,
                lanes: 1,
                continuesBefore: start < day,
                continuesAfter: end > next
            };
        }).sort((a, b) => a.top - b.top || b.height - a.height || String(a.event.event_series_id).localeCompare(String(b.event.event_series_id)));
        let cluster = [], ends = [], clusterEnd = -1;
        const finish = () => {
            cluster.forEach(item => item.lanes = ends.length);
            cluster = [];
            ends = [];
            clusterEnd = -1;
        };
        for (const item of items) {
            if (cluster.length && item.top >= clusterEnd) finish();
            let lane = ends.findIndex(end => end <= item.top);
            if (lane < 0) lane = ends.length;
            ends[lane] = item.end;
            item.lane = lane;
            cluster.push(item);
            clusterEnd = Math.max(clusterEnd, item.end);
        }
        finish();
        return items;
    }

    const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[c]));
    globalThis.CompanionCalendar = {
        MONTHS,
        WEEKDAYS,
        pad,
        dayStart,
        addDays,
        weekStart,
        sameDay,
        dateKey,
        time,
        localInput,
        monthGrid,
        selectMonth,
        yearPage,
        navigate,
        layoutEvents,
        escape
    };
})();
