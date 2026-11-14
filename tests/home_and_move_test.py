from laser_hardware import ThorlabsStage

def test_1():
    with ThorlabsStage() as stage:
        print('Before homing:', stage.position(), 'um')
        stage.home()
        print('After homing:', stage.position(), 'um')

if __name__ == '__main__':
    test_1()
