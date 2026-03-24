    active_today = await count_active_today()
    total_q = await total_quizzes()
    total_pts = await total_points_awarded()
    dist = await rank_distribution()

    ranks_order = ["rookie", "scholar", "pro", "master", "legend"]
    dist_lines = []
    for r in ranks_order:
        count = dist.get(r, 0)
        if count:
            dis
