document.addEventListener('DOMContentLoaded', function() {
    const socket = io.connect('http://localhost:5000');

    socket.on('connect', function() {
        socket.emit('fetch_kpis');
    });

    socket.on('task_started', function(data) {
        const taskId = data.task_id;
        // Optionally, start polling for status (not required if Celery emits on completion)
        socket.emit('check_task_status', taskId);
    });

    socket.on('kpi_data', function(data) {
        // Render the KPI data in the table as previously described
        renderKpiData(data);
    });

    socket.on('task_status', function(data) {
        if (data.status === 'Pending') {
            // Optionally, continue polling or show a loading indicator
            console.log('Task still in progress...');
        }
    });
});

function renderKpiData(data) {
    const kpiTablesDiv = document.getElementById('kpi-tables');
    kpiTablesDiv.innerHTML = '';  // Clear previous data

    data.forEach(device => {
        let tableHtml = `<h2>Device: ${device.device_name} (ID: ${device.device_id})</h2>`;
        tableHtml += '<table border="1"><tr><th>Minute</th><th>Average Heart Rate</th></tr>';
        
        device.avg_heart_rate_per_minute.forEach(kpi => {
            tableHtml += `<tr><td>${kpi.minute}</td><td>${kpi.avg_heartrate.toFixed(2)}</td></tr>`;
        });

        tableHtml += '</table><br>';
        kpiTablesDiv.innerHTML += tableHtml;
    });
}