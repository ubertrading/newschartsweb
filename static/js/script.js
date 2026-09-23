var srcmap = {
  '0': "",
  '1': "AF-T",
  '2': "BB",
  '3': "FF",
  '4': "RT-T",
  '5': "HH",
  '6': "ADO",
  '7': "AF-U",
  '8': "RT-U",
  '9': "HH-U",
  '10': "SYN",
  '11': "BJ",
  '12': "JA1",
  '13': "RT3",
  '14': "EG14",
  'EG14': "EG14",
  '15': "15",
  '16': "16",
  '17': "17",
  '18': "18",
  '19': "19",
  '20': "BB1",
  '21': "BB2",
  '22': "BB3",
  '23': "BB4",
  '24': "BB5",
  '25': "BB6",
  '26': "BB7",
  '27': "BB8",
  '28': "BB9",
  '29': "BB10",
  'bbg-hist': "BBG-Hist",
};



// function showCurrencyList(event) {
//   var currencyList = document.getElementById('currencySelect');
//   currencyList.style.display = 'block';
//   var button = event.target;
//   var rect = button.getBoundingClientRect();
//   currencyList.style.top = rect.bottom + 'px';
//   currencyList.style.left = rect.left + 'px';

//   currencyList.onchange = function () {
//     button.textContent = currencyList.value;
//     currencyList.style.display = 'none';
//   }

//   return false;
// }

// document.addEventListener('click', function (event) {
//   var currencyList = document.getElementById('currencySelect');
//   if (!currencyList.contains(event.target) && event.target.tagName !== 'BUTTON') {
//     currencyList.style.display = 'none';
//   }
// });

// function goGraph(f) {
//   var form = f.closest('form');
//   form['currency'].value = document.getElementById("currencySelect").value;
// }


function fixNumber(value) {
  if (value === "" || value === null) return ""
  try {
    let fv = value;
    if (typeof value === "string") {
      fv = parseFloat(value);
    }


    return parseFloat(fv.toFixed(5));
  } catch (err) {
    console.log("failed to fix number", value, err)
  }
}

function deviation(value, forecast) {
  if (!forecast) return "";

  try {
    const v = parseFloat(value);
    const f = parseFloat(forecast);

    return fixNumber(v - f);
  } catch (ex) {
    console.log("failed to convert number", ex);
  }
}



// Helper to parse URL parameters
function getUrlParameter(sParam) {
    var sPageURL = window.location.search.substring(1),
        sURLVariables = sPageURL.split('&'),
        sParameterName,
        i;

    for (i = 0; i < sURLVariables.length; i++) {
        sParameterName = sURLVariables[i].split('=');
        if (sParameterName[0] === sParam) {
            return sParameterName[1] === undefined ? true : decodeURIComponent(sParameterName[1].replace(/\+/g, ' '));
        }
    }
    return false;
}

// Shared dropdown infrastructure - only ONE Select2 instance for the entire page
var $sharedDropdownContainer = null;
var activeFormData = null;
var sharedDropdownInitialized = false;
var exactTimeFilter = null;

function initSharedDropdown() {
  // Only initialize once — no need to recreate on every data reload
  if (sharedDropdownInitialized) return;
  sharedDropdownInitialized = true;

  // Create a single floating dropdown container
  $sharedDropdownContainer = $('<div id="shared-symbol-dropdown" style="display:none; position:absolute; z-index:2000; min-width:200px;">' +
    '<select id="shared-select2" class="form-control" style="width:100%;">' +
    generateSymbols() +
    '</select>' +
    '</div>');

  $('body').append($sharedDropdownContainer);

  // Initialize Select2 once
  $('#shared-select2').select2({
    dropdownParent: $sharedDropdownContainer
  });

  // When user selects a symbol, submit the form for that row
  $('#shared-select2').on('select2:select', function (e) {
    if (activeFormData) {
      var symbol = $(this).val();
      if (symbol) {
        // Build URL and open in new tab
        var params = $.param({
          id: activeFormData.id,
          datetime: activeFormData.datetime,
          scheduled: activeFormData.scheduled,
          news: activeFormData.news,
          symbol: symbol,
          forecast_avg: activeFormData.forecast_avg,
          forecast: activeFormData.forecast,
          actual: activeFormData.actual,
          deviation: activeFormData.deviation
        });
        window.open((activeFormData.chartUrl || 'graph.php') + '?' + params, '_blank');
      }
      // Reset and hide the dropdown
      $(this).val(null).trigger('change');
      $sharedDropdownContainer.hide();
      activeFormData = null;
    }
  });

  // Close dropdown when clicking elsewhere
  $(document).on('mousedown', function (e) {
    if ($sharedDropdownContainer && $sharedDropdownContainer.is(':visible')) {
      if (!$(e.target).closest('#shared-symbol-dropdown').length &&
        !$(e.target).closest('.select2-container').length &&
        !$(e.target).hasClass('symbol-btn')) {
        $sharedDropdownContainer.hide();
        activeFormData = null;
      }
    }
  });
}

function showSymbolDropdown(btn) {
  var $btn = $(btn);
  activeFormData = {
    id: $btn.data('newsid'),
    datetime: $btn.data('datetime'),
    scheduled: $btn.data('scheduled'),
    news: $btn.data('news'),
    forecast_avg: $btn.data('forecastavg'),
    forecast: $btn.data('forecast'),
    actual: $btn.data('actual'),
    deviation: $btn.data('deviation'),
    chartUrl: $btn.data('charturl') || 'graph.php'
  };

  // Position the dropdown near the button
  var offset = $btn.offset();
  $sharedDropdownContainer.css({
    top: offset.top + $btn.outerHeight(),
    left: offset.left
  }).show();

  // Open the Select2 dropdown
  $('#shared-select2').val(null).trigger('change');
  $('#shared-select2').select2('open');
}

// Helper to HTML-escape text content (prevents XSS and broken HTML)
function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  var str = String(text);
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Country prefix to instruments mapping for multi-chart view
var prefixInstruments = {
  'US': ['USDJPY', 'XAUUSD', 'EURUSD', 'SPX500', 'NAS100', 'US30', 'US2000', 'BTCUSD', '10USNote'],
  'JP': ['USDJPY', 'EURJPY', 'GBPJPY', 'CHFJPY', 'CADJPY', 'AUDJPY', 'JPN225'],
  'CN': ['USDCNH', 'CHN50'],
  'CA': ['USDCAD', 'EURCAD', 'CADJPY', 'GBPCAD', 'AUDCAD', 'CADCHF'],
  'AU': ['AUDUSD', 'AUDJPY', 'EURAUD', 'GBPAUD', 'AUDNZD', 'AUS200'],
  'UK': ['GBPUSD', 'GBPJPY', 'GBPCHF', 'EURGBP', 'UK100'],
  'EU': ['EURUSD', 'EURJPY', 'EURGBP', 'EURCHF', 'GER30', 'EUSTX50'],
  'DE': ['EURUSD', 'EURJPY', 'EURGBP', 'EURCHF', 'GER30', 'EUSTX50'],
  'FR': ['EURUSD', 'EURJPY', 'EURGBP', 'EURCHF', 'FRA40', 'GER40', 'EUSTX50'],
  'NO': ['USDNOK', 'EURNOK', 'NOKSEK', 'NOKJPY'],
  'SE': ['USDSEK', 'EURSEK', 'NOKSEK', 'SEKJPY'],
  'NZ': ['NZDUSD', 'NZDJPY', 'EURNZD', 'GBPNZD', 'NZDCHF', 'NZDCAD', 'AUDNZD'],
  'CH': ['USDCHF', 'CHFJPY', 'EURCHF', 'GBPCHF', 'AUDCHF', 'CADCHF'],
  'CZ': ['USDCZK', 'EURCZK'],
  'HU': ['USDHUF', 'EURHUF'],
  'PL': ['USDPLN', 'EURPLN'],
  'MX': ['USDMXN', 'EURMXN'],
  'TR': ['USDTRY', 'EURTRY', 'TRYJPY'],
  'ZA': ['USDZAR', 'EURZAR', 'ZARJPY']
};

function openMultiChart(btn) {
  var $btn = $(btn);
  var newsName = $btn.data('news');
  var prefix = String(newsName).substring(0, 2).toUpperCase();
  var instruments = prefixInstruments[prefix];

  if (!instruments) {
    alert('No multi-chart mapping for prefix "' + prefix + '". Use Select... instead.');
    return;
  }

  var params = $.param({
    id: $btn.data('newsid'),
    datetime: $btn.data('datetime'),
    scheduled: $btn.data('scheduled'),
    news: newsName,
    forecast_avg: $btn.data('forecastavg'),
    forecast: $btn.data('forecast'),
    actual: $btn.data('actual'),
    deviation: $btn.data('deviation'),
    instruments: instruments.join(',')
  });
  window.open('multigraph.php?' + params, '_blank');
}

function openDukasChart(btn) {
  var $btn = $(btn);
  var params = $.param({
    id: $btn.data('newsid'),
    datetime: $btn.data('datetime'),
    scheduled: $btn.data('scheduled'),
    news: $btn.data('news'),
    symbol: 'EURUSD',
    forecast_avg: $btn.data('forecastavg'),
    forecast: $btn.data('forecast'),
    actual: $btn.data('actual'),
    deviation: $btn.data('deviation')
  });
  window.open('graph_dukas.php?' + params, '_blank');
}

function openDukasMultiChart(btn) {
  var $btn = $(btn);
  var newsName = $btn.data('news');
  var prefix = String(newsName).substring(0, 2).toUpperCase();
  var instruments = prefixInstruments[prefix];

  if (!instruments) {
    alert('No multi-chart mapping for prefix "' + prefix + '". Use Select... instead.');
    return;
  }
  
  // Dukascopy does not support NZDCAD or AUDNZD tick data, so we strip them out specifically for the DUKA+ charts
  instruments = instruments.filter(function(sym) { return sym !== 'NZDCAD' && sym !== 'AUDNZD'; });

  var params = $.param({
    id: $btn.data('newsid'),
    datetime: $btn.data('datetime'),
    scheduled: $btn.data('scheduled'),
    news: newsName,
    forecast_avg: $btn.data('forecastavg'),
    forecast: $btn.data('forecast'),
    actual: $btn.data('actual'),
    deviation: $btn.data('deviation'),
    instruments: instruments.join(',')
  });
  window.open('multigraph_dukas.php?' + params, '_blank');
}

function toggleGroup(safeKey) {
  var rows = $('.group-row-' + safeKey);
  var icon = $('#icon-' + safeKey);
  if (rows.is(':visible')) {
    rows.hide();
    icon.removeClass('fa-minus').addClass('fa-plus');
  } else {
    rows.show();
    icon.removeClass('fa-plus').addClass('fa-minus');
  }
}

function toggleAllGroups(expand) {
  if (expand) {
    $('tr[class*="group-row-"]').show();
    $('i[id^="icon-"]').removeClass('fa-plus').addClass('fa-minus');
  } else {
    $('tr[class*="group-row-"]').hide();
    $('i[id^="icon-"]').removeClass('fa-minus').addClass('fa-plus');
  }
}

function getCalendar() {
  var dtfrom = $('#datetimepicker1').val();
  var dtto = $('#datetimepicker2').val();
  var newsId = $('#newsId').val();
  var news = $('#news').val();
  var site = $('#site').val();

  $('#reload').find('i').addClass('fa-spin');
  var data = {
    'action': 'getCalendar',
    'datefrom': dtfrom,
    'dateto': dtto,
    'newsId': newsId,
    'news': news,
    'site': site
  };
  if (exactTimeFilter) {
    data['exact_time'] = exactTimeFilter;
  }
  $.post('nrreport.php', data,
    function (data, textStatus, jqXHR) {
      if (data != null) {
        if (data['status'] == 'success') {
          var rows = data['data'];
          
          var groupCounts = {};
          for (var i in rows) {
            var r = rows[i];
            var dtevent_i_temp = moment(parseInt(r['event_time']));
            var dtevent_temp = dtevent_i_temp.tz('America/New_York').format("MM/DD/YY HH:mm");
            var key_temp = r.news_id + "_" + dtevent_temp;
            groupCounts[key_temp] = (groupCounts[key_temp] || 0) + 1;
          }

          var lastNewsId = null;

          // Build all rows as a single HTML string for maximum performance
          var htmlParts = [];

          for (var i in rows) {
            var row = rows[i];
            var dtevent_i = moment(parseInt(row['event_time']));
            var dtevent = dtevent_i.tz('America/New_York').format("MM/DD/YY HH:mm");
            var dttimestamp_i = moment(parseInt(row['timestamp']));
            var dttimestamp = dttimestamp_i.tz('America/New_York').format("HH:mm:ss.SSS");
            var dttimestamp_hover = dttimestamp_i.tz('America/New_York').format("MM/DD HH:mm:ss.SSS");

            var dttimestampnews = dttimestamp_i.utc().format("YYYY-MM-DD HH:mm:ss.SSS");
            var dttimestampnews_scheduled = dtevent_i.utc().format("YYYY-MM-DD HH:mm:ss.SSS");

            // for events with no timestamp
            if (row['timestamp'] == 0) {
              dttimestamp = "";
              dttimestamp_hover = "";
              dttimestampnews = "";
            }

            var _src = row['source'];
            var src = _src;
            if (_src in srcmap) {
              src = srcmap[_src];
            }

            // Build the graph cell content
            var graphCell = '';
            var dev = deviation(row.value, row.forecast);
            
            var key = row.news_id + "_" + dtevent;
            var isFirstInGroup = (key !== lastNewsId);
            var safeKey = key.replace(/[^a-zA-Z0-9]/g, '-');
            
            if (isFirstInGroup) {
              var dataAttrs =
                'data-newsid="' + escapeHtml(row['news_id']) + '" ' +
                'data-datetime="' + escapeHtml(dttimestampnews) + '" ' +
                'data-scheduled="' + escapeHtml(dttimestampnews_scheduled) + '" ' +
                'data-news="' + escapeHtml(row.news) + '" ' +
                'data-forecastavg="' + escapeHtml(fixNumber(row.forecast_avg)) + '" ' +
                'data-forecast="' + escapeHtml(fixNumber(row.forecast)) + '" ' +
                'data-actual="' + escapeHtml(fixNumber(row.value)) + '" ' +
                'data-deviation="' + escapeHtml(dev) + '"';

              graphCell = '<div style="white-space: nowrap;">' + 
                '<button type="button" class="btn btn-sm btn-outline-light symbol-btn" ' +
                dataAttrs + ' data-charturl="graph.php" onclick="showSymbolDropdown(this)">FXCM</button> ' +
                '<button type="button" class="btn btn-sm btn-outline-light" ' +
                dataAttrs + ' onclick="openMultiChart(this)">FXCM+</button> ' +
                '<button type="button" class="btn btn-sm btn-outline-light symbol-btn" ' +
                dataAttrs + ' data-charturl="graph_dukas.php" onclick="showSymbolDropdown(this)">DUKA</button> ' +
                '<button type="button" class="btn btn-sm btn-outline-light" ' +
                dataAttrs + ' onclick="openDukasMultiChart(this)">DUKA+</button>' +
                '<button type="button" class="btn btn-sm btn-outline-warning ml-1" title="Edit Data" ' +
                'data-newsid="' + escapeHtml(row.news_id) + '" ' +
                'data-eventtime="' + escapeHtml(row.event_time) + '" ' +
                'data-source="' + escapeHtml(row.source) + '" ' +
                'data-value="' + escapeHtml(row.value) + '" ' +
                'data-forecast="' + escapeHtml(row.forecast) + '" ' +
                'data-forecastavg="' + escapeHtml(row.forecast_avg) + '" ' +
                'data-prior="' + escapeHtml(row.prior) + '" ' +
                'onclick="openEditModal(this)"><i class="fa fa-pencil"></i></button>' +
                '</div>';
            }

            var toggleBtn = '';
            if (isFirstInGroup && groupCounts[key] > 1) {
              toggleBtn = '<button type="button" class="btn btn-sm btn-outline-light mr-1 p-1 flex-shrink-0" style="line-height:1; height: 22px; width: 22px;" onclick="toggleGroup(\'' + safeKey + '\')"><i id="icon-' + safeKey + '" class="fa fa-plus" style="font-size: 10px;"></i></button> ';
            }

            var trClass = isFirstInGroup ? '' : ('group-row-' + safeKey);
            var trStyle = isFirstInGroup ? '' : 'style="display:none;"';

            var historyUrlId = 'nrreport.html?newsId=' + encodeURIComponent(row.news_id) + '&datefrom=2000-01-01';
            var idLink = '<a href="' + historyUrlId + '" target="_blank" style="color: inherit; text-decoration: none;">' + escapeHtml(row.news_id) + '</a>';
            var idContent = '<div class="d-flex align-items-center flex-nowrap">' + toggleBtn + '<span>' + idLink + '</span></div>';

            var historyUrlName = 'nrreport.html?news=' + encodeURIComponent(row.news) + '&datefrom=2000-01-01';
            var nameLink = '<a href="' + historyUrlName + '" target="_blank" style="color: inherit; text-decoration: none;">' + escapeHtml(row.news) + '</a>';

            var exactDate = dtevent_i.format("YYYY-MM-DD");
            var exactTimeMs = dtevent_i.valueOf();
            var historyUrlDate = 'nrreport.html?datefrom=' + exactDate + '&dateto=' + exactDate + '&exactTime=' + exactTimeMs;
            var dateLink = '<a href="' + historyUrlDate + '" target="_blank" style="color: inherit; text-decoration: none;">' + escapeHtml(dtevent) + '</a>';

            var devLink = dev !== "" ? '<a href="deviation_graph.php?newsId=' + encodeURIComponent(row.news_id) + '&news=' + encodeURIComponent(row.news) + '&v=' + Date.now() + '" target="_blank" style="color: inherit; text-decoration: none;">' + escapeHtml(dev) + '</a>' : '';
            var actualVal = fixNumber(row.value);
            var actualLink = (actualVal !== "" && actualVal !== undefined && actualVal !== null) ? '<a href="actual_graph.php?newsId=' + encodeURIComponent(row.news_id) + '&news=' + encodeURIComponent(row.news) + '&v=' + Date.now() + '" target="_blank" style="color: inherit; text-decoration: none;">' + escapeHtml(actualVal) + '</a>' : '';

            htmlParts.push(
              '<tr class="' + trClass + '" ' + trStyle + '>' +
              '<td style="white-space: nowrap;">' + idContent + '</td>' +
              '<td style="white-space: nowrap;">' + dateLink + '</td>' +
              '<td><span title="' + escapeHtml(dttimestamp_hover) + '">' + escapeHtml(dttimestamp) + '</span></td>' +
              '<td style="white-space: nowrap;">' + nameLink + '</td>' +
              '<td>' + escapeHtml(fixNumber(row.prior)) + '</td>' +
              '<td>' + escapeHtml(fixNumber(row.forecast_avg)) + '</td>' +
              '<td>' + escapeHtml(fixNumber(row.forecast)) + '</td>' +
              '<td>' + actualLink + '</td>' +
              '<td>' + devLink + '</td>' +
              '<td>' + escapeHtml(src) + '</td>' +
              '<td>' + graphCell + '</td>' +
              '</tr>'
            );

            lastNewsId = key;
          }

          // Single DOM write — innerHTML is faster than fragment with jQuery objects
          $('table#calendar').find('tbody')[0].innerHTML = htmlParts.join('');

          // Initialize the shared dropdown once (not on every reload)
          initSharedDropdown();

          // Respect the global expand/collapse state
          var isExpandAll = $('#expandAll').is(':checked');
          if (isExpandAll) {
            toggleAllGroups(true);
          }
        }
      }
      $('#reload').find('i').removeClass('fa-spin');
    },
    'json');
}

$(function () {
  moment.tz.add(["America/New_York|EST EDT EWT EPT|50 40 40 40|01010101010101010101010101010101010101010101010102301010101010101010101010101010101010101010101010101010101010101010101010101010101010101010101010101010101010101010101010101010101010101010101010101010101010101010101010101010101010101010|-261t0 1nX0 11B0 1nX0 11B0 1qL0 1a10 11z0 1qN0 WL0 1qN0 11z0 1o10 11z0 1o10 11z0 1o10 11z0 1o10 11z0 1qN0 11z0 1o10 11z0 1o10 11z0 1o10 11z0 1o10 11z0 1qN0 WL0 1qN0 11z0 1o10 11z0 1o10 11z0 1o10 11z0 1o10 11z0 1qN0 WL0 1qN0 11z0 1o10 11z0 RB0 8x40 iv0 1o10 11z0 1o10 11z0 1o10 11z0 1o10 11z0 1qN0 WL0 1qN0 11z0 1o10 11z0 1o10 11z0 1o10 11z0 1o10 1fz0 1cN0 1cL0 1cN0 1cL0 1cN0 1cL0 1cN0 1cL0 1cN0 1fz0 1cN0 1cL0 1cN0 1cL0 1cN0 1cL0 1cN0 1cL0 1cN0 1fz0 1a10 1fz0 1cN0 1cL0 1cN0 1cL0 1cN0 1cL0 1cN0 1cL0 1cN0 1fz0 1cN0 1cL0 1cN0 1cL0 s10 1Vz0 LB0 1BX0 1cN0 1fz0 1a10 1fz0 1cN0 1cL0 1cN0 1cL0 1cN0 1cL0 1cN0 1cL0 1cN0 1fz0 1a10 1fz0 1cN0 1cL0 1cN0 1cL0 1cN0 1cL0 14p0 1lb0 14p0 1nX0 11B0 1nX0 11B0 1nX0 14p0 1lb0 14p0 1lb0 14p0 1nX0 11B0 1nX0 11B0 1nX0 14p0 1lb0 14p0 1lb0 14p0 1lb0 14p0 1nX0 11B0 1nX0 11B0 1nX0 14p0 1lb0 14p0 1lb0 14p0 1nX0 11B0 1nX0 11B0 1nX0 Rd0 1zb0 Op0 1zb0 Op0 1zb0 Rd0 1zb0 Op0 1zb0 Op0 1zb0 Op0 1zb0 Op0 1zb0 Op0 1zb0 Rd0 1zb0 Op0 1zb0 Op0 1zb0 Op0 1zb0 Op0 1zb0 Rd0 1zb0 Op0 1zb0 Op0 1zb0 Op0 1zb0 Op0 1zb0 Op0 1zb0 Rd0 1zb0 Op0 1zb0 Op0 1zb0 Op0 1zb0 Op0 1zb0 Rd0 1zb0 Op0 1zb0 Op0 1zb0 Op0 1zb0 Op0 1zb0 Op0 1zb0|21e6"
  ]);

  var urlDateFrom = getUrlParameter('datefrom');
  var dt1 = urlDateFrom ? moment(urlDateFrom) : moment().day(1);
  $('#datetimepicker1').datetimepicker({
    format: 'YYYY-MM-DD',
    icons: {
      date: 'fa fa-calendar'
    },
    useCurrent: false,
    date: dt1
  });

  var urlDateTo = getUrlParameter('dateto');
  var dt2 = urlDateTo ? moment(urlDateTo) : moment().day(7);
  $('#datetimepicker2').datetimepicker({
    format: 'YYYY-MM-DD',
    icons: {
      date: 'fa fa-calendar'
    },
    useCurrent: false,
    date: dt2
  });

  $(document).ready(function () {
    var urlNewsId = getUrlParameter('newsId');
    if (urlNewsId) {
      $('#newsId').val(urlNewsId);
    }
    var urlNews = getUrlParameter('news');
    if (urlNews) {
      $('#news').val(urlNews);
    }
    var urlSite = getUrlParameter('site');
    if (urlSite) {
      $('#site').val(urlSite);
    }
    var urlExactTime = getUrlParameter('exactTime');
    if (urlExactTime) {
      exactTimeFilter = urlExactTime;
    }

    // Initialize dark theme checkbox (default: on)
    var darkPref = localStorage.getItem('darkTheme');
    $('#darkTheme').prop('checked', darkPref !== 'false');
    getCalendar();
  });
  $('#newsId').change(function () {
    getCalendar();
  });
  $('#news').change(function () {
    getCalendar();
  });
  $('#datetimepicker1').on('dp.change', function () {
    exactTimeFilter = null;
    getCalendar();
  });
  $('#datetimepicker2').on('dp.change', function () {
    exactTimeFilter = null;
    getCalendar();
  });
  $('#site').on('change', function () {
    getCalendar();
  });
  $('#reload').click(function () {
    getCalendar();
  });
});

function openEditModal(btn) {
  var $btn = $(btn);
  $('#edit_news_id').val($btn.data('newsid'));
  $('#edit_event_time').val($btn.data('eventtime'));
  $('#edit_source').val($btn.data('source'));
  $('#edit_actual').val($btn.data('value'));
  $('#edit_forecast').val($btn.data('forecast'));
  $('#edit_forecast_avg').val($btn.data('forecastavg'));
  $('#edit_prior').val($btn.data('prior'));
  $('#editEventModal').modal('show');
}

function saveEventEdits() {
  var data = {
    action: 'updateEvent',
    news_id: $('#edit_news_id').val(),
    event_time: $('#edit_event_time').val(),
    source: $('#edit_source').val(),
    value: $('#edit_actual').val(),
    forecast: $('#edit_forecast').val(),
    forecast_avg: $('#edit_forecast_avg').val(),
    prior: $('#edit_prior').val()
  };

  $.post('nrreport.php', data, function(resp) {
    if (resp && resp.status === 'success') {
      $('#editEventModal').modal('hide');
      getCalendar();
    } else {
      alert("Error updating event.");
    }
  }, 'json');
}

