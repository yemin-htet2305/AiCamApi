from flask import Flask,request,jsonify
from flask_cors import CORS
from pymongo import MongoClient
from datetime import datetime


app = Flask(__name__)
CORS(app)

# ADD after app = Flask(__name__)
client = MongoClient("mongodb://localhost:27017/")
db = client["aicam_db"]
collection = db["daily_counts"]

@app.route("/api/seed/bulk", methods=['POST'])
def add_bulk_data():
    data = request.get_json()
    entries = data.get('entries')  # expects a list

    if not entries or not isinstance(entries, list):
        return jsonify({"error": "entries must be a non-empty list"}), 400

    records = [
        {
            "date": entry.get('date'),
            "entry_count": entry.get('entries'),
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        for entry in entries
    ]

    result = collection.insert_many(records)
    return jsonify({
        "message": f"{len(result.inserted_ids)} entries added"
    })

@app.route("/api/seed", methods=['POST'])
def add_data():
    data = request.get_json()
    date = data.get('date')
    entries = data.get('entries')

    collection.insert_one({
        "date": date,
        "entry_count": entries,
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    return jsonify({"message": "Entry added"})

@app.route("/api/history", methods=['GET'])
def history():
    date = request.args.get('date')
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    sort = request.args.get('sort', 'desc')
    min_entries = request.args.get('min_entries')
    max_entries = request.args.get('max_entries')

    query = {}

    if date:
        query["date"] = date
    elif from_date and to_date:
        query["date"] = {"$gte": from_date, "$lte": to_date}
    elif from_date:
        query["date"] = {"$gte": from_date}
    elif to_date:
        query["date"] = {"$lte": to_date}

    if min_entries is not None or max_entries is not None:
        query["entry_count"] = {}
        if min_entries is not None:
            query["entry_count"]["$gte"] = int(min_entries)
        if max_entries is not None:
            query["entry_count"]["$lte"] = int(max_entries)

    sort_dir = 1 if sort == "asc" else -1
    # rows = list(collection.find(query, {"_id": 0}).sort("date", sort_dir))
    rows = list(collection.find(query).sort("date", sort_dir))

    # data = [
    #     {"id": str(row.get("_id", "")), "date": row["date"], "entries": row["entry_count"], "savedAt": row["saved_at"]}
    #     for row in rows
    # ]
    data = [
        {"id": str(row["_id"]), "date": row["date"], "entries": row["entry_count"], "savedAt": row["saved_at"]}
        for row in rows
    ]
    return jsonify({"count": len(data), "data": data})

@app.route("/api/stats/summary", methods=['GET'])
def stats_summary():
    rows = list(collection.find({}, {"_id": 0, "entry_count": 1}))

    if not rows:
        return jsonify({"error": "No data found"}), 404

    counts = [r["entry_count"] for r in rows]
    return jsonify({
        "total_days":    len(counts),
        "total_entries": sum(counts),
        "avg_per_day":   round(sum(counts) / len(counts), 2),
        "min_entries":   min(counts),
        "max_entries":   max(counts)
    })

@app.route("/api/stats/daily-avg", methods=['GET'])
def stats_daily_avg():
    month = request.args.get('month')

    query = {}
    if month:
        # match dates like "2024-01-xx"
        query["date"] = {"$regex": f"^{month}"}

    rows = list(collection.find(query, {"_id": 0, "entry_count": 1}))

    if not rows:
        return jsonify({"error": "No data found"}), 404

    counts = [r["entry_count"] for r in rows]
    return jsonify({
        "month":     month or "all-time",
        "daily_avg": round(sum(counts) / len(counts), 2)
    })

@app.route("/api/stats/peak", methods=['GET'])
def stats_peak():
    n = request.args.get('n', 1, type=int)

    # rows = list(collection.find({}, {"_id": 0}).sort("entry_count", -1).limit(n))
    rows = list(collection.find({}).sort("entry_count", -1).limit(n))

    if not rows:
        return jsonify({"error": "No data found"}), 404

    #
    data = [
        {"id": str(r["_id"]), "date": r["date"], "entries": r["entry_count"], "savedAt": r["saved_at"]}
        for r in rows
    ]
    return jsonify({"top_n": n, "peak": data})

@app.route("/api/stats/trend", methods=['GET'])
def stats_trend():
    days = request.args.get('days', 7, type=int)

    rows = list(collection.find({}, {"_id": 0, "date": 1, "entry_count": 1}).sort("date", -1).limit(days))

    if len(rows) < 2:
        return jsonify({"error": "Not enough data for trend"}), 400

    rows = rows[::-1]  # chronological order

    first_half  = rows[:days // 2]
    second_half = rows[days // 2:]
    avg_first   = sum(r["entry_count"] for r in first_half)  / len(first_half)
    avg_second  = sum(r["entry_count"] for r in second_half) / len(second_half)

    direction  = "up" if avg_second > avg_first else "down" if avg_second < avg_first else "flat"
    change_pct = round(((avg_second - avg_first) / avg_first) * 100, 1) if avg_first > 0 else 0

    return jsonify({
        "days":       days,
        "direction":  direction,
        "change_pct": change_pct,
        "data": [{"date": r["date"], "entries": r["entry_count"]} for r in rows]
    })

if __name__ == "__main__":
    app.run(debug=True,port=5001, use_reloader=False)

