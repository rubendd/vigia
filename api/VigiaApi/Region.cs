namespace VigiaApi;

/// <summary>
/// Region the instance covers. It only drives what the web shows (name, initial map view);
/// which detections exist is decided by the ingestion's REGION setting.
/// </summary>
public sealed record Region(string Key, string Name, double[][] Bounds)
{
    private static readonly Dictionary<string, Region> Known = new(StringComparer.OrdinalIgnoreCase)
    {
        // Bounds are [[south, west], [north, east]], the format Leaflet's fitBounds expects.
        ["andalucia"] = new("andalucia", "Andalucía", [[35.90, -7.55], [38.75, -1.60]]),
        ["espana"] = new("espana", "España", [[27.50, -18.30], [43.90, 4.50]]),
    };

    public static Region FromKey(string? key) =>
        Known.TryGetValue(string.IsNullOrWhiteSpace(key) ? "andalucia" : key.Trim(), out var region)
            ? region
            : throw new InvalidOperationException($"Unknown region '{key}'. Use one of: {string.Join(", ", Known.Keys)}.");
}
