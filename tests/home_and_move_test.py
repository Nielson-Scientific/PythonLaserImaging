from laser_hardware import ThorlabsStage

def test_1():
    stage = ThorlabsStage()
    print('Stage position:', stage.position(), 'um')
    stage.home()
    stage.close()

if __name__ == '__main__':
    test_1()
