from laser_hardware import ThorlabsStage

def test_1():
    with ThorlabsStage() as stage:
        print('Stage position:', stage.position(), 'um')

if __name__ == '__main__':
    test_1()
