using Npgsql;
using VigiaApi;

var builder = WebApplication.CreateBuilder(args);

var connectionString = builder.Configuration.GetConnectionString("Vigia")
    ?? "Host=localhost;Port=5432;Database=vigia;Username=vigia;Password=vigia";

var region = Region.FromKey(builder.Configuration["Vigia:Region"]);

builder.Services.AddSingleton(NpgsqlDataSource.Create(connectionString));
builder.Services.AddSingleton<HotspotQueries>();
builder.Services.AddSingleton(region);
builder.Services.AddCors(o => o.AddDefaultPolicy(p => p.AllowAnyOrigin().AllowAnyHeader().WithMethods("GET")));

var app = builder.Build();

app.UseCors();
app.UseDefaultFiles();
app.UseStaticFiles();

const int MaxHours = 240;

static IResult Invalid(string field, string message) =>
    Results.ValidationProblem(new Dictionary<string, string[]> { [field] = [message] });

// Shared validation for endpoints that accept the map filters.
static async Task<(IResult? Error, string? Province, int MinRank)> ParseFiltersAsync(
    HotspotQueries q, int hours, string? province, string? minConfidence, CancellationToken ct)
{
    if (hours is < 1 or > MaxHours)
        return (Invalid("hours", $"Must be between 1 and {MaxHours}."), null, 0);

    if (!HotspotQueries.TryGetConfidenceRank(minConfidence, out var minRank))
        return (Invalid("minConfidence", "Use low, nominal or high."), null, 0);

    if (string.IsNullOrWhiteSpace(province))
        return (null, null, minRank);

    var canonical = await q.ResolveProvinceAsync(province, ct);
    return canonical is null
        ? (Invalid("province", "Unknown province. Load municipal boundaries or check /api/provinces."), null, 0)
        : (null, canonical, minRank);
}

var api = app.MapGroup("/api");

api.MapGet("/config", (Region r) => Results.Ok(new { region = r.Key, name = r.Name, bounds = r.Bounds }));

api.MapGet("/health", async (NpgsqlDataSource ds, CancellationToken ct) =>
{
    try
    {
        await using var cmd = ds.CreateCommand("SELECT 1");
        await cmd.ExecuteScalarAsync(ct);
        return Results.Ok(new { status = "ok" });
    }
    catch (NpgsqlException)
    {
        return Results.Problem("Database unavailable", statusCode: StatusCodes.Status503ServiceUnavailable);
    }
});

api.MapGet("/hotspots", async (HotspotQueries q, CancellationToken ct, int hours = 24, string? province = null, string? minConfidence = null) =>
{
    var (error, canonical, minRank) = await ParseFiltersAsync(q, hours, province, minConfidence, ct);
    if (error is not null) return error;

    var geoJson = await q.GetHotspotsGeoJsonAsync(hours, canonical, minRank, ct);
    return Results.Text(geoJson, "application/geo+json");
});

api.MapGet("/stats", async (HotspotQueries q, CancellationToken ct, int hours = 24, string? province = null, string? minConfidence = null) =>
{
    var (error, canonical, minRank) = await ParseFiltersAsync(q, hours, province, minConfidence, ct);
    if (error is not null) return error;

    return Results.Ok(await q.GetStatsAsync(hours, canonical, minRank, ct));
});

api.MapGet("/provinces", async (HotspotQueries q, CancellationToken ct, int hours = 24, string? minConfidence = null) =>
{
    var (error, _, minRank) = await ParseFiltersAsync(q, hours, null, minConfidence, ct);
    if (error is not null) return error;

    return Results.Ok(await q.GetProvinceCountsAsync(hours, minRank, ct));
});

app.Run();
