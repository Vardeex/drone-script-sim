"""Przelot między matami Tello EDU (Mission Pads) - wersja dla symulatora.

Uruchom w symulatorze ze sceną ``mission_pads`` (UI -> Przeszkody albo
``./start.bat`` i wybór sceny). Scena ma cztery maty na podłodze:

* m1 w ``(0, 0)`` - start drona,
* m2 w ``(120, 0)``,
* m3 w ``(0, 120)``,
* m4 w ``(120, 120)``, obrócona o 90° (jej oś X to ``+Y`` świata).

Układ projektu: x = przód, y = lewo, z = góra, start w (0, 0, 0). Komendy
``*_mid`` liczą pozycję **względem maty** (x = przód maty, y = lewo maty,
z = góra od maty) - tak jak Tello SDK 2.0.

Zasięg wykrywania (założenie modelu, patrz README): promień 30 cm od środka
maty i wysokość 30-120 cm nad matą. Dlatego po ``go_xyz_speed_mid(..., 0, ...)``
dron wisi 60 cm nad środkiem maty i widzi ją dalej, a loty ``move_*`` wykonujemy
tak, żeby nie oddalić się od maty bardziej niż o 30 cm.
"""

from djitellopy import Tello

#: wysokość lotu nad matą [cm] - w zasięgu wykrywania (30-120 cm)
FLY_HEIGHT = 60
SPEED = 40


def show(tello: Tello, label: str) -> None:
    """Wypisz widzianą matę i odległości (x, y, z) w jej układzie."""
    pad = tello.get_mission_pad_id()
    if pad == -1:
        print(f"{label}: brak maty")
        return
    print(f"{label}: m{pad} x={tello.get_mission_pad_distance_x()} "
          f"y={tello.get_mission_pad_distance_y()} z={tello.get_mission_pad_distance_z()}")


def main() -> None:
    tello = Tello()
    tello.connect()
    tello.enable_mission_pads()             # mon
    tello.set_mission_pad_detection_direction(0)   # 0 = tylko kamera dolna
    tello.takeoff()                        # 80 cm nad podłogą
    tello.set_speed(SPEED)
    try:
        # start dokładnie nad m1: SDK liczy z od podłogi, więc 60 cm nad matą
        tello.go_xyz_speed_mid(0, 0, FLY_HEIGHT, SPEED, 1)
        show(tello, "nad m1")

        # przelot do m2 - 120 cm z przodu, ta sama wysokość.
        # Uwaga: m2 jest 120 cm od m1, czyli poza zasięgiem kamery (30 cm) -
        # dlatego lot dzielimy na krótkie odcinki (30 cm), po których dron
        # kolejno przechodzi nad krawędzią zasięgu obu mat. Pierwszy odcinek
        # liczymy względem m1, kolejne względem m2 (dron jest już nad m2).
        tello.go_xyz_speed_mid(30, 0, FLY_HEIGHT, SPEED, 1)   # 30 cm przed m1
        tello.move_forward(60)                                # 90 cm przed m1
        tello.go_xyz_speed_mid(0, 0, FLY_HEIGHT, SPEED, 2)    # nad m2
        tello.move_back(30)                                   # cofnięcie nad m2
        tello.go_xyz_speed_mid(0, 0, FLY_HEIGHT, SPEED, 2)
        show(tello, "nad m2")

        # z m2 do m3 (przekątna nie jest potrzebna): wracamy nad m1, potem
        # na lewo od m1 do m3. Odcinki po 40 cm: 120 - 40 - 40 - 40 = 0.
        tello.move_back(40)                # 80 cm przed m1
        tello.move_back(40)                # 40 cm przed m1
        tello.move_back(40)                # nad m1 (120 cm od m2)
        show(tello, "z powrotem nad m1")
        tello.move_left(40)                # 40 cm w lewo od m1
        tello.move_left(40)                # 80 cm w lewo od m1
        tello.move_left(40)                # nad m3 (120 cm od m1)
        tello.go_xyz_speed_mid(0, 0, FLY_HEIGHT, SPEED, 3)
        show(tello, "nad m3")

        # m4 leży 120 cm przed m3 (x = +120, y = +120) - dron stoi nad m3
        # z kursem +X, więc dolatujemy dwoma odcinkami ``move_forward``.
        tello.move_forward(60)             # 60 cm przed m3
        tello.move_forward(60)             # nad krawędzią m4
        tello.go_xyz_speed_mid(0, 0, FLY_HEIGHT, SPEED, 4)
        show(tello, "nad m4 (obrócona)")

        tello.disable_mission_pads()       # moff - dalej nie wykrywamy
        print("po wyłączeniu:", tello.get_mission_pad_id())

        # kontrola z geometrii: nad m4 dron powinien być w (120, 120), 60 cm nad
        # podłogą - jest nad matą, więc po ponownym włączeniu widzi m4
        tello.enable_mission_pads()
        print("na końcu:", tello.get_mission_pad_id())
    finally:
        tello.land()


if __name__ == "__main__":
    main()
