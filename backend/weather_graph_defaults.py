# Definitions for the Matplotlib Graph styles

GRAPH_SERIES_DEFAULTS = {
    'temp': {
        'parameter': 'temp', 'axis': 'left', 'color': 'black', 
        'legend_label': 'Temp', 'line_style': 'solid', 'linewidth': 2
    },
    'feels_like': {
        'parameter': 'feels_like', 'axis': 'left', 'color': 'gray', 
        'legend_label': 'Feel', 'line_style': 'dotted', 'linewidth': 1.5
    },
    'rain': {
        'parameter': 'rain', 'axis': 'right', 'color': 'blue', 
        'legend_label': 'Rain', 'plot_type': 'line', 'linewidth': 1.5,
        'fill_to_zero': True, 'alpha': 0.3
    },
    'wind_speed': {
        'parameter': 'wind_speed', 'axis': 'right', 'color': 'green', 
        'legend_label': 'Wind', 'line_style': 'solid', 'linewidth': 1.5
    },
    # FIXED: Singular 'wind_gust'
    'wind_gust': {
        'parameter': 'wind_gust', 'axis': 'right', 'color': 'red', 
        'legend_label': 'Gusts', 'line_style': 'dashed', 'linewidth': 1.0
    },
    'humidity': {
        'parameter': 'humidity', 'axis': 'right', 'color': '#555555', 
        'legend_label': 'Hum', 'line_style': 'dashed', 'linewidth': 1
    },
    'pressure': {
        'parameter': 'pressure', 'axis': 'right', 'color': 'purple', 
        'legend_label': 'hPa', 'line_style': 'dashdot', 'linewidth': 1
    }
}