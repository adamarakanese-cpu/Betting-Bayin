from datafc import eloratings


print("👑 BETTING BAYIN")
print("🔬 ELO HISTORY RAW DATA DEBUG")
print()

teams = [
    "Spain",
    "Argentina",
]

for team in teams:

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"🌍 TEAM: {team}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    try:
        df = eloratings.country_matches_data(team)

        print("\n📋 COLUMNS:")
        print(list(df.columns))

        print("\n📦 SHAPE:")
        print(df.shape)

        print("\n🔎 FIRST 5 ROWS:")
        print(
            df.head(5).to_string(
                index=False
            )
        )

        print("\n🔎 LAST 5 ROWS:")
        print(
            df.tail(5).to_string(
                index=False
            )
        )

        print("\n🧩 TEAM A UNIQUE SAMPLE:")
        print(
            df["team_a"]
            .dropna()
            .astype(str)
            .unique()[:20]
        )

        print("\n🧩 TEAM B UNIQUE SAMPLE:")
        print(
            df["team_b"]
            .dropna()
            .astype(str)
            .unique()[:20]
        )

        print("\n📈 TEAM A RATING SAMPLE:")
        print(
            df["team_a_rating"]
            .dropna()
            .head(10)
            .tolist()
        )

        print("\n📉 TEAM B RATING SAMPLE:")
        print(
            df["team_b_rating"]
            .dropna()
            .head(10)
            .tolist()
        )

        print("\n🗓 DATE SAMPLE:")
        print(
            df["date"]
            .dropna()
            .head(10)
            .tolist()
        )

    except Exception as error:

        print(
            f"\n❌ ERROR: {error}"
        )

    print()


print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("✅ RAW DEBUG COMPLETE")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")