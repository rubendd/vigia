using Npgsql;
using NpgsqlTypes;

namespace VigiaApi;

/// <summary>
/// Read-only queries against PostGIS. GeoJSON is assembled inside PostgreSQL so the API
/// streams it straight to the client without mapping geometry types in .NET.
/// Provinces come from the loaded municipal boundaries, so the code works for any region.
/// </summary>
public sealed class HotspotQueries(NpgsqlDataSource dataSource)
{
    private static readonly Dictionary<string, int> ConfidenceRank = new(StringComparer.OrdinalIgnoreCase)
    {
        ["low"] = 0, ["nominal"] = 1, ["high"] = 2,
    };

    public static bool TryGetConfidenceRank(string? value, out int rank)
    {
        rank = 0;
        return string.IsNullOrWhiteSpace(value) || ConfidenceRank.TryGetValue(value, out rank);
    }

    // Filters shared by the map and the counters, so both always describe the same set of hotspots.
    private const string FilterSql = """
        h.acquired_at >= now() - make_interval(hours => @hours)
          AND (@province::text IS NULL OR m.province = @province::text)
          AND (CASE h.confidence WHEN 'high' THEN 2 WHEN 'nominal' THEN 1 ELSE 0 END) >= @minRank
        """;

    private static void AddFilterParameters(NpgsqlCommand cmd, int hours, string? province, int minRank)
    {
        cmd.Parameters.AddWithValue("hours", hours);
        cmd.Parameters.Add(new NpgsqlParameter("province", NpgsqlDbType.Text) { Value = (object?)province ?? DBNull.Value });
        cmd.Parameters.AddWithValue("minRank", minRank);
    }

    /// <summary>Returns the province name exactly as stored, or null if it does not exist.</summary>
    public async Task<string?> ResolveProvinceAsync(string name, CancellationToken ct)
    {
        await using var cmd = dataSource.CreateCommand(
            "SELECT province FROM municipalities WHERE lower(province) = lower(@name) LIMIT 1");
        cmd.Parameters.AddWithValue("name", name.Trim());
        return await cmd.ExecuteScalarAsync(ct) as string;
    }

    private const string HotspotsSql = $"""
        SELECT json_build_object(
                 'type', 'FeatureCollection',
                 'features', COALESCE(json_agg(s.feature), '[]'::json)
               )::text
        FROM (
            SELECT json_build_object(
                     'type', 'Feature',
                     'geometry', ST_AsGeoJSON(h.geom)::json,
                     'properties', json_build_object(
                         'id', h.id,
                         'acquiredAt', h.acquired_at,
                         'confidence', h.confidence,
                         'frp', h.frp,
                         'brightness', h.brightness,
                         'satellite', h.satellite,
                         'source', h.source,
                         'daynight', h.daynight,
                         'municipality', m.name,
                         'province', m.province
                     )
                   ) AS feature
            FROM hotspots h
            LEFT JOIN municipalities m ON m.id = h.municipality_id
            WHERE {FilterSql}
            ORDER BY h.acquired_at DESC
            LIMIT 5000
        ) s
        """;

    public async Task<string> GetHotspotsGeoJsonAsync(int hours, string? province, int minRank, CancellationToken ct)
    {
        await using var cmd = dataSource.CreateCommand(HotspotsSql);
        AddFilterParameters(cmd, hours, province, minRank);
        var result = await cmd.ExecuteScalarAsync(ct);
        return result as string ?? """{"type":"FeatureCollection","features":[]}""";
    }

    private const string StatsSql = $"""
        SELECT count(*)                                         AS total,
               count(*) FILTER (WHERE h.confidence = 'high')    AS high,
               max(h.acquired_at)                               AS latest_detection,
               (SELECT max(ingested_at) FROM hotspots)          AS last_ingest
        FROM hotspots h
        LEFT JOIN municipalities m ON m.id = h.municipality_id
        WHERE {FilterSql}
        """;

    public async Task<StatsDto> GetStatsAsync(int hours, string? province, int minRank, CancellationToken ct)
    {
        await using var cmd = dataSource.CreateCommand(StatsSql);
        AddFilterParameters(cmd, hours, province, minRank);
        await using var reader = await cmd.ExecuteReaderAsync(ct);
        await reader.ReadAsync(ct);
        return new StatsDto(
            hours,
            reader.GetInt64(0),
            reader.GetInt64(1),
            reader.IsDBNull(2) ? null : reader.GetFieldValue<DateTimeOffset>(2),
            reader.IsDBNull(3) ? null : reader.GetFieldValue<DateTimeOffset>(3));
    }

    // Every loaded province appears, with zero when it has no detections; busiest first.
    private const string ProvinceCountsSql = """
        SELECT p.province, count(h.id) AS hotspots
        FROM (SELECT DISTINCT province FROM municipalities) p
        LEFT JOIN municipalities m ON m.province = p.province
        LEFT JOIN hotspots h ON h.municipality_id = m.id
             AND h.acquired_at >= now() - make_interval(hours => @hours)
             AND (CASE h.confidence WHEN 'high' THEN 2 WHEN 'nominal' THEN 1 ELSE 0 END) >= @minRank
        GROUP BY p.province
        ORDER BY hotspots DESC, p.province
        """;

    public async Task<IReadOnlyList<ProvinceCountDto>> GetProvinceCountsAsync(int hours, int minRank, CancellationToken ct)
    {
        var result = new List<ProvinceCountDto>();
        await using var cmd = dataSource.CreateCommand(ProvinceCountsSql);
        cmd.Parameters.AddWithValue("hours", hours);
        cmd.Parameters.AddWithValue("minRank", minRank);
        await using var reader = await cmd.ExecuteReaderAsync(ct);
        while (await reader.ReadAsync(ct))
        {
            result.Add(new ProvinceCountDto(reader.GetString(0), reader.GetInt64(1)));
        }
        return result;
    }
}

public sealed record StatsDto(int Hours, long Total, long High, DateTimeOffset? LatestDetection, DateTimeOffset? LastIngest);

public sealed record ProvinceCountDto(string Province, long Hotspots);
