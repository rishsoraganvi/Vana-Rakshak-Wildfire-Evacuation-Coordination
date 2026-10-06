from ingest_worker.clustering import cluster_hotspots


def test_cluster_groups_nearby_points():
    points = [
        {"lat": 11.700 + i * 0.001, "lon": 76.600 + i * 0.001, "frp": 10.0 + i}
        for i in range(5)
    ]
    clusters = cluster_hotspots(points, eps_deg=0.01, min_samples=3)
    assert len(clusters) == 1
    assert clusters[0].point_count == 5
    assert clusters[0].mean_frp is not None
    assert round(clusters[0].mean_frp, 1) == 12.0


def test_cluster_separates_distant_points():
    # 4 points near 11.7N, 4 points near 12.1N (~44 km apart)
    cluster1 = [
        {"lat": 11.700 + i * 0.001, "lon": 76.600 + i * 0.001, "frp": 20.0}
        for i in range(4)
    ]
    cluster2 = [
        {"lat": 12.100 + i * 0.001, "lon": 76.600 + i * 0.001, "frp": 15.0}
        for i in range(4)
    ]
    clusters = cluster_hotspots(cluster1 + cluster2, eps_deg=0.01, min_samples=3)
    assert len(clusters) == 2
    counts = sorted([c.point_count for c in clusters])
    assert counts == [4, 4]


def test_cluster_empty_returns_empty():
    assert cluster_hotspots([]) == []


def test_cluster_below_min_samples_excluded():
    points = [
        {"lat": 11.700, "lon": 76.600, "frp": 10.0},
        {"lat": 11.701, "lon": 76.601, "frp": 10.0},
    ]
    assert cluster_hotspots(points, eps_deg=0.01, min_samples=3) == []
