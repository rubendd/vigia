FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY VigiaApi/VigiaApi.csproj VigiaApi/
RUN dotnet restore VigiaApi/VigiaApi.csproj
COPY VigiaApi/ VigiaApi/
RUN dotnet publish VigiaApi/VigiaApi.csproj -c Release -o /app --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /app .
ENV ASPNETCORE_URLS=http://+:8080
EXPOSE 8080
ENTRYPOINT ["dotnet", "VigiaApi.dll"]
