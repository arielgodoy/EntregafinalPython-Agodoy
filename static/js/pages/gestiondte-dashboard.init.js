(function () {
    function colors(id) {
        var element = document.getElementById(id);
        if (!element) return [];
        var values = JSON.parse(element.getAttribute('data-colors') || '[]');
        return values.map(function (value) {
            var token = value.replace(' ', '');
            return token.indexOf(',') === -1
                ? getComputedStyle(document.documentElement).getPropertyValue(token) || token
                : token;
        });
    }

    function money(value) {
        return '$ ' + Number(value || 0).toLocaleString('es-CL', { maximumFractionDigits: 0 });
    }

    function emptyOption() {
        return { title: { text: 'Sin datos para el período seleccionado', left: 'center', top: 'middle', textStyle: { color: '#878a99', fontSize: 14, fontWeight: 'normal' } } };
    }

    function setChart(chart, option, data) {
        chart.clear();
        chart.setOption(data.length ? option : emptyOption());
    }

    document.addEventListener('DOMContentLoaded', function () {
        var root = document.getElementById('dte-dashboard');
        if (!root || typeof echarts === 'undefined') return;
        var select = document.getElementById('dte-dashboard-periodo');
        var loading = document.querySelector('.dte-dashboard-loading');
        var endpoint = root.dataset.endpoint;
        var chartIds = ['dte-chart-evolucion', 'dte-chart-estados', 'dte-chart-actividad', 'dte-chart-cesionarios'];
        var charts = chartIds.map(function (id) { return echarts.init(document.getElementById(id)); });

        function update(periodo) {
            loading.classList.add('is-loading');
            fetch(endpoint + '?periodo=' + encodeURIComponent(periodo), { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
                .then(function (response) {
                    if (!response.ok) throw new Error('No fue posible cargar el dashboard.');
                    return response.json();
                })
                .then(function (data) {
                    var kpis = data.kpis || {};
                    document.querySelectorAll('[data-kpi]').forEach(function (element) {
                        var key = element.dataset.kpi;
                        element.textContent = key === 'monto_total' || key === 'monto_promedio' ? money(kpis[key]) : (key === 'ultima_cesion' && kpis[key] ? new Date(kpis[key]).toLocaleString('es-CL') : (kpis[key] || 0));
                    });
                    var evolution = data.evolucion || [];
                    setChart(charts[0], { color: colors('dte-chart-evolucion'), tooltip: { trigger: 'axis', formatter: function (items) { return items[0].axisValue + '<br>' + money(items[0].value); } }, grid: { left: '3%', right: '3%', bottom: '8%', containLabel: true }, xAxis: { type: 'category', data: evolution.map(function (item) { return item.periodo; }) }, yAxis: { type: 'value' }, series: [{ name: 'Monto cedido', type: 'line', smooth: true, areaStyle: {}, data: evolution.map(function (item) { return Number(item.monto || 0); }) }] }, evolution);

                    var states = data.estados_rpetc || [];
                    setChart(charts[1], { color: colors('dte-chart-estados'), tooltip: { trigger: 'item', formatter: function (item) { return item.name + '<br>' + item.value + ' cesiones<br>' + money(states[item.dataIndex].monto); } }, legend: { bottom: 0 }, series: [{ name: 'Estado RPETC', type: 'pie', radius: ['42%', '70%'], itemStyle: { borderRadius: 4, borderColor: '#fff', borderWidth: 2 }, data: states.map(function (item) { return { name: item.estado_cesion || 'Sin estado', value: item.cantidad }; }) }] }, states);

                    setChart(charts[2], { color: colors('dte-chart-actividad'), tooltip: { trigger: 'axis', formatter: function (items) { return items[0].axisValue + items.map(function (item) { return '<br>' + item.seriesName + ': ' + (item.seriesName === 'Monto cedido' ? money(item.value) : item.value); }).join(''); } }, legend: { bottom: 0 }, grid: { left: '3%', right: '4%', bottom: '12%', containLabel: true }, xAxis: { type: 'category', data: evolution.map(function (item) { return item.periodo; }) }, yAxis: [{ type: 'value', name: 'Cantidad' }, { type: 'value', name: 'Monto' }], series: [{ name: 'Cantidad', type: 'bar', data: evolution.map(function (item) { return item.cantidad; }) }, { name: 'Monto cedido', type: 'line', yAxisIndex: 1, data: evolution.map(function (item) { return Number(item.monto || 0); }) }] }, evolution);

                    var top = data.cesionarios_top || [];
                    setChart(charts[3], { color: colors('dte-chart-cesionarios'), tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: function (items) { return items[0].name + '<br>' + money(items[0].value); } }, grid: { left: '4%', right: '5%', bottom: '3%', containLabel: true }, xAxis: { type: 'value' }, yAxis: { type: 'category', inverse: true, data: top.map(function (item) { return (item.cesionario_razon_social || '-') + ' (' + (item.cesionario_rut || '-') + ')'; }) }, series: [{ name: 'Monto cedido', type: 'bar', data: top.map(function (item) { return Number(item.monto || 0); }) }] }, top);
                })
                .catch(function (error) { console.error(error); })
                .finally(function () { loading.classList.remove('is-loading'); });
        }

        select.addEventListener('change', function () { update(select.value); });
        window.addEventListener('resize', function () { charts.forEach(function (chart) { chart.resize(); }); });
        update(select.value || 'mes');
    });
}());
