package harmonica

type FPS int

func FPS(value int) FPS {
	return FPS(value)
}

type Spring struct{}

func NewSpring(_ FPS, _ float64, _ float64) Spring {
	return Spring{}
}

func (Spring) Update(_ float64, _ float64, target float64) (float64, float64) {
	return target, 0
}
